"""
Behavioral model + tests for FR-2: Synaptic Crossbar.
"""
import pytest
import math

INT16_MAX = 0x7FFF
INT16_MIN = -0x8000

def to_s16(v: int) -> int:
    return max(INT16_MIN, min(INT16_MAX, v))

def sign_extend(val: int, width: int) -> int:
    """Sign-extend a `width`-bit value to Python arbitrary-precision int."""
    if val & (1 << (width - 1)):
        val -= (1 << width)
    return val


class SynapticCrossbar:
    """
    Cycle-accurate behavioral model of synaptic_crossbar (FR-2).
    """
    def __init__(self, n_pre=4, n_post=4, weight_width=8, data_width=16):
        self.N_PRE = n_pre
        self.N_POST = n_post
        self.WEIGHT_WIDTH = weight_width
        self.DATA_WIDTH = data_width
        # Weight matrix [pre][post], stored as signed integers
        self.weights = [[0] * n_post for _ in range(n_pre)]
        self.o_currents = [0] * n_post
        self.o_valid = 0

    def reset(self):
        self.weights = [[0] * self.N_POST for _ in range(self.N_PRE)]
        self.o_currents = [0] * self.N_POST
        self.o_valid = 0

    def cfg_write(self, pre: int, post: int, weight: int):
        """Write a weight (signed WEIGHT_WIDTH-bit value)."""
        self.weights[pre][post] = sign_extend(weight & ((1 << self.WEIGHT_WIDTH) - 1),
                                              self.WEIGHT_WIDTH)

    def tick(self, i_spikes: int, i_valid: bool):
        """
        Advance one clock cycle. Output is registered (valid next cycle).
        Returns (o_currents, o_valid) representing the REGISTERED outputs.
        """
        if i_valid:
            new_currents = []
            acc_bits = self.DATA_WIDTH + math.ceil(math.log2(max(self.N_PRE, 2)))
            acc_max = (1 << (acc_bits - 1)) - 1
            acc_min = -(1 << (acc_bits - 1))
            for j in range(self.N_POST):
                acc = 0
                for i in range(self.N_PRE):
                    if (i_spikes >> i) & 1:
                        w = sign_extend(
                            self.weights[i][j] & ((1 << self.WEIGHT_WIDTH) - 1),
                            self.WEIGHT_WIDTH
                        )
                        w_ext = w  # sign-extended to DATA_WIDTH
                        acc += w_ext
                # Saturate to DATA_WIDTH signed range
                new_currents.append(to_s16(acc))
            self.o_currents = new_currents
            self.o_valid = 1
        else:
            self.o_valid = 0
        return list(self.o_currents), self.o_valid


# ---------------------------------------------------------------------------
# Tier 1 – Basic Functionality
# ---------------------------------------------------------------------------

class TestSynapticCrossbarBasicFunctionality:

    def test_spec_example_all_weights_16_spikes_1010(self):
        """Spec example: all weights=0x10=16, spikes=0b1010 → each current=32."""
        cb = SynapticCrossbar()
        for pre in range(4):
            for post in range(4):
                cb.cfg_write(pre, post, 0x10)
        currents, valid = cb.tick(0b1010, True)
        assert valid == 1, "o_valid should be 1 after i_valid tick"
        for j in range(4):
            assert currents[j] == 32, \
                f"Post-neuron {j}: expected 32 (0x0020), got {currents[j]}"

    def test_zero_spikes_zero_currents(self):
        """No active spikes → all output currents are zero."""
        cb = SynapticCrossbar()
        for pre in range(4):
            for post in range(4):
                cb.cfg_write(pre, post, 0x7F)
        currents, valid = cb.tick(0b0000, True)
        assert valid == 1, "o_valid must still assert"
        for j, c in enumerate(currents):
            assert c == 0, f"Post-neuron {j}: expected 0 with no spikes, got {c}"

    def test_single_spike_single_weight(self):
        """Only spike[0] active, weight[0][2]=50 → current[2]=50."""
        cb = SynapticCrossbar()
        cb.cfg_write(0, 2, 50)
        currents, _ = cb.tick(0b0001, True)
        assert currents[2] == 50, \
            f"Expected current[2]=50, got {currents[2]}"
        assert currents[0] == 0 and currents[1] == 0 and currents[3] == 0, \
            "Other currents should be 0"

    def test_o_valid_single_cycle_pulse(self):
        """o_valid is 1 for one cycle then 0 when no further i_valid."""
        cb = SynapticCrossbar()
        _, v1 = cb.tick(0b0001, True)
        _, v2 = cb.tick(0b0001, False)
        assert v1 == 1, "o_valid should be 1 after i_valid"
        assert v2 == 0, "o_valid should be 0 when i_valid was not asserted prior cycle"

    def test_reset_clears_weights_and_valid(self):
        """Reset zeroes all weights and deasserts o_valid."""
        cb = SynapticCrossbar()
        for pre in range(4):
            for post in range(4):
                cb.cfg_write(pre, post, 0x7F)
        cb.tick(0b1111, True)
        cb.reset()
        assert cb.o_valid == 0, "o_valid should be 0 after reset"
        for row in cb.weights:
            for w in row:
                assert w == 0, f"All weights should be 0 after reset, got {w}"

    def test_negative_weights_reduce_current(self):
        """Negative (inhibitory) weights produce negative currents."""
        cb = SynapticCrossbar()
        cb.cfg_write(0, 0, -20)   # signed -20
        currents, _ = cb.tick(0b0001, True)
        assert currents[0] < 0, \
            f"Negative weight should give negative current, got {currents[0]}"
        assert currents[0] == -20, \
            f"Expected current=-20, got {currents[0]}"

    def test_config_takes_effect_next_tick(self):
        """Weight written via cfg_write is used on the immediately following tick."""
        cb = SynapticCrossbar()
        cb.cfg_write(1, 1, 100)
        currents, _ = cb.tick(0b0010, True)
        assert currents[1] == 100, \
            f"Config must take effect; expected 100, got {currents[1]}"


# ---------------------------------------------------------------------------
# Tier 2 – Edge Cases
# ---------------------------------------------------------------------------

class TestSynapticCrossbarEdgeCases:

    def test_all_ones_spikes_sum_all_rows(self):
        """All spikes active → current is sum of all weights in that column."""
        cb = SynapticCrossbar()
        for pre in range(4):
            cb.cfg_write(pre, 0, 10)  # each weight = 10
        currents, _ = cb.tick(0b1111, True)
        assert currents[0] == 40, f"Sum of 4 weights of 10 should be 40, got {currents[0]}"

    def test_saturation_positive_large_weights(self):
        """Sum exceeds INT16_MAX → saturate to 0x7FFF."""
        cb = SynapticCrossbar()
        for pre in range(4):
            cb.cfg_write(pre, 0, 0x7F)  # 127 each, 4*127=508 > 255
        currents, _ = cb.tick(0b1111, True)
        assert currents[0] <= INT16_MAX, \
            f"Expected saturation at {INT16_MAX}, got {currents[0]}"

    def test_saturation_negative_large_weights(self):
        """Sum below INT16_MIN → saturate to 0x8000."""
        cb = SynapticCrossbar()
        for pre in range(4):
            cb.cfg_write(pre, 0, sign_extend(0x80, 8))  # -128 each
        currents, _ = cb.tick(0b1111, True)
        assert currents[0] >= INT16_MIN, \
            f"Expected saturation at {INT16_MIN}, got {currents[0]}"

    def test_mixed_positive_negative_weights_cancel(self):
        """Equal positive and negative weights sum to zero current."""
        cb = SynapticCrossbar()
        cb.cfg_write(0, 0, 50)
        cb.cfg_write(1, 0, -50)
        currents, _ = cb.tick(0b0011, True)
        assert currents[0] == 0, \
            f"Cancelling weights must give 0 current, got {currents[0]}"

    def test_weight_update_between_ticks(self):
        """Weight update between two ticks takes effect on second tick."""
        cb = SynapticCrossbar()
        cb.cfg_write(0, 0, 10)
        c1, _ = cb.tick(0b0001, True)
        cb.cfg_write(0, 0, 20)   # update
        c2, _ = cb.tick(0b0001, True)
        assert c1[0] == 10, f"First tick: expected 10, got {c1[0]}"
        assert c2[0] == 20, f"Second tick with updated weight: expected 20, got {c2[0]}"

    def test_no_valid_no_output_change(self):
        """When i_valid is 0, o_valid must be 0 (currents may hold previous)."""
        cb = SynapticCrossbar()
        cb.cfg_write(0, 0, 99)
        cb.tick(0b0001, True)
        _, v = cb.tick(0b0001, False)
        assert v == 0, "o_valid must be 0 when i_valid was not asserted"

    def test_weight_sign_extension_8bit(self):
        """8-bit weight 0x80 (-128 in two's complement) sign-extends correctly."""
        cb = SynapticCrossbar()
        cb.cfg_write(0, 0, 0x80)   # should be -128 after sign extension
        currents, _ = cb.tick(0b0001, True)
        assert currents[0] == -128, \
            f"0x80 should sign-extend to -128, got {currents[0]}"

    def test_diagonal_weight_matrix_no_crosstalk(self):
        """Diagonal weights: each spike only drives its own post-neuron."""
        cb = SynapticCrossbar()
        for i in range(4):
            cb.cfg_write(i, i, 64)
        currents, _ = cb.tick(0b0001, True)  # only spike[0]
        assert currents[0] == 64, f"Diagonal: expected current[0]=64, got {currents[0]}"
        for j in range(1, 4):
            assert currents[j] == 0, \
                f"Diagonal: expected current[{j}]=0 (no crosstalk), got {currents[j]}"

    def test_all_zero_weights_always_zero_currents(self):
        """With all weights zero, all spikes produce zero currents."""
        cb = SynapticCrossbar()
        currents, _ = cb.tick(0b1111, True)
        for j, c in enumerate(currents):
            assert c == 0, f"All-zero weights: current[{j}] should be 0, got {c}"

    def test_output_valid_latency_exactly_one_cycle(self):
        """o_valid asserts exactly one cycle after i_valid."""
        cb = SynapticCrossbar()
        # Cycle 0: i_valid=0
        _, v0 = cb.tick(0, False)
        assert v0 == 0, "Cycle 0: o_valid should be 0"
        # Cycle 1: i_valid=1
        _, v1 = cb.tick(0b0001, True)
        assert v1 == 1, "Cycle 1: o_valid should be 1 (one cycle after i_valid)"
        # Cycle 2: i_valid=0
        _, v2 = cb.tick(0, False)
        assert v2 == 0, "Cycle 2: o_valid should be 0 (i_valid was 0)"


# ---------------------------------------------------------------------------
# Tier 3 – Large-Scale Tests
# ---------------------------------------------------------------------------

class TestSynapticCrossbarLargeScale:

    def test_10000_ticks_accumulation_correctness(self):
        """Feed known spike patterns for 10000 ticks; check cumulative validity."""
        cb = SynapticCrossbar()
        for i in range(4):
            cb.cfg_write(i, i, 1)  # identity: weight[i][i]=1
        spike_pattern = 0b0101  # spikes on axons 0 and 2
        for tick_num in range(10_000):
            currents, valid = cb.tick(spike_pattern, True)
            assert valid == 1, f"Tick {tick_num}: o_valid should be 1"
            assert currents[0] == 1, f"Tick {tick_num}: current[0] should be 1"
            assert currents[1] == 0, f"Tick {tick_num}: current[1] should be 0"
            assert currents[2] == 1, f"Tick {tick_num}: current[2] should be 1"
            assert currents[3] == 0, f"Tick {tick_num}: current[3] should be 0"

    def test_large_scale_saturation_never_wraps(self):
        """Max weights + all spikes active: saturated output never wraps."""
        cb = SynapticCrossbar()
        for pre in range(4):
            for post in range(4):
                cb.cfg_write(pre, post, 0x7F)
        for _ in range(10_000):
            currents, _ = cb.tick(0b1111, True)
            for j, c in enumerate(currents):
                assert c == INT16_MAX, \
                    f"Max weights, all spikes: expected saturation={INT16_MAX}, got {c}"

    def test_weight_updates_applied_immediately_large_scale(self):
        """10000 weight updates, each followed by a tick — always uses latest weight."""
        cb = SynapticCrossbar()
        for k in range(1, 10_001):
            weight = (k % 127) + 1  # cycles through 1..127
            cb.cfg_write(0, 0, weight)
            currents, _ = cb.tick(0b0001, True)
            assert currents[0] == weight, \
                f"Iteration {k}: expected current={weight}, got {currents[0]}"
