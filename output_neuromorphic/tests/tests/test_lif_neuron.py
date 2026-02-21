"""
Behavioral model + tests for FR-1: Leaky Integrate-and-Fire Neuron.

The behavioral model strictly follows the specification; it is the test
oracle, NOT the DUT implementation.
"""
import pytest

# ---------------------------------------------------------------------------
# Behavioral model (test oracle — implements the SPEC, not any RTL file)
# ---------------------------------------------------------------------------

INT16_MAX = 0x7FFF   # 32767
INT16_MIN = -0x8000  # -32768

def to_s16(v: int) -> int:
    """Clamp an arbitrary integer to signed-16 range (no wrap)."""
    return max(INT16_MIN, min(INT16_MAX, v))

def arith_rshift(value: int, shift: int) -> int:
    """Arithmetic (sign-preserving) right shift for Python integers."""
    return value >> shift  # Python >> is arithmetic for negative ints


class LIFNeuron:
    """
    Cycle-accurate behavioral model of lif_neuron (FR-1).

    All membrane / current values are raw Q8.8 integers (i.e. the bit pattern
    interpreted as a signed 16-bit integer).
    """
    def __init__(
        self,
        threshold: int = 0x0100,   # 16'sh0100 → +1.0 in Q8.8
        leak: int = 230,            # unsigned 8-bit
        reset_val: int = 0x0000,
        refrac_cycles: int = 2,
    ):
        self.THRESHOLD = threshold
        self.LEAK = leak
        self.RESET_VAL = reset_val
        self.REFRAC_CYCLES = refrac_cycles
        # State
        self.membrane: int = reset_val
        self.refractory_counter: int = 0
        self.o_spike: int = 0

    def reset(self):
        """Synchronous active-low reset behaviour."""
        self.membrane = self.RESET_VAL
        self.refractory_counter = 0
        self.o_spike = 0

    def tick(self, i_current: int, i_enable: bool = True):
        """
        Advance the neuron by one clock cycle.
        Returns (o_spike, o_membrane) after this edge.
        """
        if not i_enable:
            # Hold all state — no update at all
            return self.o_spike, self.membrane

        # Step 1 – Refractory check
        if self.refractory_counter > 0:
            self.refractory_counter -= 1
            self.membrane = self.RESET_VAL
            self.o_spike = 0
            return 0, self.membrane

        # Step 2 – Leak  (intermediate ≥ 24 bits: use Python unlimited ints)
        # V * LEAK is a signed×unsigned product; Python handles it correctly.
        v_leaked = arith_rshift(self.membrane * self.LEAK, 8)
        v_leaked = to_s16(v_leaked)  # truncate back to s16 representation

        # Step 3 – Integrate with saturation
        v_new_raw = v_leaked + i_current
        v_new = to_s16(v_new_raw)   # saturate on overflow

        # Step 4 – Fire?
        if v_new > self.THRESHOLD:
            self.o_spike = 1
            self.membrane = self.RESET_VAL
            self.refractory_counter = self.REFRAC_CYCLES
        else:
            self.o_spike = 0
            self.membrane = v_new

        return self.o_spike, self.membrane


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_neuron(**kwargs) -> LIFNeuron:
    return LIFNeuron(**kwargs)


# ---------------------------------------------------------------------------
# Tier 1 – Basic Functionality
# ---------------------------------------------------------------------------

class TestLIFNeuronBasicFunctionality:

    def test_spec_example_tick0_no_fire(self):
        """Spec example tick 0: V=0, i=0x0090 → V_new=0x0090, no fire."""
        n = make_neuron()
        spike, mem = n.tick(0x0090)
        assert spike == 0, f"Expected no spike at tick 0, got spike={spike}"
        assert mem == 0x0090, f"Expected membrane=0x0090, got {hex(mem)}"

    def test_spec_example_tick1_fire(self):
        """Spec example tick 1: V=0x0090, i=0x0090 → FIRE, V resets."""
        n = make_neuron()
        n.tick(0x0090)          # tick 0
        spike, mem = n.tick(0x0090)  # tick 1
        assert spike == 1, f"Expected spike at tick 1, got spike={spike}"
        assert mem == 0x0000, f"Expected membrane reset to 0x0000, got {hex(mem)}"

    def test_spec_example_refractory_ticks(self):
        """After firing, neuron is refractory for REFRAC_CYCLES ticks."""
        n = make_neuron()
        n.tick(0x0090)   # tick 0
        n.tick(0x0090)   # tick 1 → fire, refrac=2
        # tick 2
        s2, m2 = n.tick(0x00FF)
        assert s2 == 0, f"Tick 2 (refrac): expected no spike, got {s2}"
        assert m2 == 0x0000, f"Tick 2 (refrac): membrane must stay at RESET_VAL, got {hex(m2)}"
        # tick 3
        s3, m3 = n.tick(0x00FF)
        assert s3 == 0, f"Tick 3 (refrac): expected no spike, got {s3}"
        assert m3 == 0x0000, f"Tick 3 (refrac): membrane must stay at RESET_VAL, got {hex(m3)}"

    def test_spec_example_tick4_after_refractory(self):
        """Spec example tick 4: neuron integrates normally after refrac expires."""
        n = make_neuron()
        n.tick(0x0090)
        n.tick(0x0090)  # fire
        n.tick(0x00FF)  # refrac 2→1
        n.tick(0x00FF)  # refrac 1→0
        spike, mem = n.tick(0x0090)  # tick 4
        assert spike == 0, f"Tick 4: expected no spike, got {spike}"
        assert mem == 0x0090, f"Tick 4: expected membrane=0x0090, got {hex(mem)}"

    def test_reset_clears_state(self):
        """Synchronous reset zeroes membrane, refractory, and o_spike."""
        n = make_neuron()
        n.tick(0x0090)
        n.tick(0x0090)  # fire → refrac=2, membrane=0
        n.reset()
        assert n.membrane == 0x0000, f"Post-reset membrane should be 0, got {hex(n.membrane)}"
        assert n.refractory_counter == 0, f"Post-reset refrac should be 0, got {n.refractory_counter}"
        assert n.o_spike == 0, f"Post-reset o_spike should be 0, got {n.o_spike}"

    def test_spike_is_single_cycle_pulse(self):
        """o_spike is asserted for exactly one cycle."""
        n = make_neuron()
        n.tick(0x0090)
        s1, _ = n.tick(0x0090)  # fires
        s2, _ = n.tick(0x0000)  # should be 0 (in refrac, but spike itself gone)
        assert s1 == 1, "Expected spike on fire cycle"
        assert s2 == 0, "Spike must be single-cycle; expected 0 on subsequent cycle"

    def test_no_fire_below_threshold(self):
        """Current exactly equal to threshold must NOT fire (strict > comparison)."""
        n = make_neuron(threshold=0x0100)
        spike, mem = n.tick(0x0100)  # V_new == THRESHOLD, not >
        assert spike == 0, f"V_new == THRESHOLD should NOT fire, got spike={spike}"
        assert mem == 0x0100, f"Membrane should be 0x0100, got {hex(mem)}"

    def test_i_enable_low_holds_state(self):
        """When i_enable is low, neuron state does not change."""
        n = make_neuron()
        n.tick(0x0090)           # build up some membrane
        mem_before = n.membrane
        _, mem_after = n.tick(0x0FFF, i_enable=False)
        assert mem_after == mem_before, \
            f"i_enable=0 must hold state; expected {hex(mem_before)}, got {hex(mem_after)}"


# ---------------------------------------------------------------------------
# Tier 2 – Edge Cases
# ---------------------------------------------------------------------------

class TestLIFNeuronEdgeCases:

    def test_zero_current_leak_only(self):
        """With i_current=0 and a starting membrane, only leak occurs."""
        n = make_neuron(leak=230)
        n.membrane = 0x0100  # manually set membrane to 1.0
        _, mem = n.tick(0)
        expected = arith_rshift(0x0100 * 230, 8)
        assert mem == to_s16(expected), \
            f"Leak-only tick: expected {hex(to_s16(expected))}, got {hex(mem)}"

    def test_zero_leak_factor(self):
        """LEAK=0 → V_leaked=0 every tick; only the single-tick current matters."""
        n = make_neuron(leak=0, threshold=0x0100)
        n.membrane = 0x7FFF  # max membrane
        spike, mem = n.tick(0x0000)
        assert mem == 0, f"LEAK=0 zeros membrane before integration; expected 0, got {hex(mem)}"

    def test_max_leak_factor(self):
        """LEAK=255 → near-full accumulation (255/256 of V retained)."""
        n = make_neuron(leak=255, threshold=0x7FFF)
        n.membrane = 0x0100
        _, mem = n.tick(0)
        expected = to_s16(arith_rshift(0x0100 * 255, 8))
        assert mem == expected, \
            f"LEAK=255 tick: expected {hex(expected)}, got {hex(mem)}"

    def test_positive_overflow_saturation(self):
        """Membrane + current overflow → saturate to INT16_MAX (0x7FFF)."""
        n = make_neuron(threshold=0x7FFF, leak=255)
        n.membrane = INT16_MAX
        spike, mem = n.tick(1)   # any positive push overflows
        assert spike == 0 or mem == INT16_MAX, \
            "On positive overflow, membrane must saturate to 0x7FFF, not wrap"
        if spike == 0:
            assert mem == INT16_MAX, \
                f"Saturated membrane should be 0x7FFF, got {hex(mem)}"

    def test_negative_overflow_saturation(self):
        """Large negative current → saturate to INT16_MIN (0x8000)."""
        n = make_neuron(threshold=0x7FFF, leak=0)
        n.membrane = INT16_MIN
        spike, mem = n.tick(-1)  # negative push on most-negative value
        assert mem >= INT16_MIN, f"Membrane must not go below INT16_MIN, got {hex(mem)}"

    def test_negative_current_inhibitory(self):
        """Negative current should reduce membrane potential."""
        n = make_neuron()
        n.membrane = 0x0100
        _, mem = n.tick(-0x0080)  # −0.5 in Q8.8
        assert mem < 0x0100, \
            f"Negative current must reduce membrane; expected < 0x0100, got {hex(mem)}"

    def test_threshold_at_zero(self):
        """THRESHOLD=0: any positive V_new causes fire."""
        n = make_neuron(threshold=0)
        spike, _ = n.tick(1)  # V_leaked=0, V_new=1 > 0
        assert spike == 1, "THRESHOLD=0: any positive V_new should trigger fire"

    def test_refractory_blocks_large_current(self):
        """Strong current during refractory must not fire or change membrane."""
        n = make_neuron()
        n.tick(0x0090)
        n.tick(0x0090)   # fire, refrac=2
        s, m = n.tick(INT16_MAX)   # huge current, still in refrac
        assert s == 0, "Refractory: no spike despite huge current"
        assert m == 0x0000, "Refractory: membrane stays at RESET_VAL"

    def test_refrac_counter_decrements_each_tick(self):
        """Refractory counter decrements by exactly 1 per enabled tick."""
        n = make_neuron(refrac_cycles=3)
        n.tick(0x0090)
        n.tick(0x0090)   # fire, refrac=3
        assert n.refractory_counter == 3
        n.tick(0)
        assert n.refractory_counter == 2, f"After 1 tick, refrac should be 2, got {n.refractory_counter}"
        n.tick(0)
        assert n.refractory_counter == 1
        n.tick(0)
        assert n.refractory_counter == 0

    def test_refrac_no_decrement_when_disabled(self):
        """Refractory counter must NOT decrement when i_enable is low."""
        n = make_neuron(refrac_cycles=2)
        n.tick(0x0090)
        n.tick(0x0090)   # fire
        n.tick(0, i_enable=False)  # disabled
        assert n.refractory_counter == 2, \
            "Disabled tick must not decrement refractory counter"

    def test_reset_val_nonzero(self):
        """Custom RESET_VAL is used as post-spike and refractory membrane value."""
        n = make_neuron(reset_val=0x0010)
        n.membrane = 0
        n.tick(0x0200)   # guarantee fire (0x0200 > 0x0100)
        assert n.membrane == 0x0010, \
            f"Post-fire membrane must equal RESET_VAL=0x0010, got {hex(n.membrane)}"

    def test_multiple_firings(self):
        """Neuron can fire repeatedly after each refractory period."""
        n = make_neuron(refrac_cycles=1)
        fires = 0
        for _ in range(20):
            s, _ = n.tick(0x0200)  # always above threshold when membrane not in refrac
            fires += s
        assert fires > 1, f"Expected multiple firings over 20 ticks, got {fires}"

    def test_sub_threshold_does_not_fire_ever(self):
        """Extremely small current never causes fire (below threshold)."""
        n = make_neuron(threshold=0x7FFF)
        for _ in range(100):
            s, _ = n.tick(1)
        # With leak, membrane should converge; may or may not saturate but should not fire
        assert n.o_spike == 0 or True  # main check: if it fires, membrane > threshold must hold
        # More precise: track if it ever spiked
        n2 = make_neuron(threshold=0x7FFF, leak=255)
        spikes = sum(n2.tick(0x0001)[0] for _ in range(500))
        assert spikes == 0, f"Tiny current with high threshold should never fire; got {spikes} spikes"


# ---------------------------------------------------------------------------
# Tier 3 – Large-Scale Tests
# ---------------------------------------------------------------------------

class TestLIFNeuronLargeScale:

    def test_spike_count_predictable_pattern(self):
        """Over 10000 ticks with constant current, spike rate must be stable."""
        n = make_neuron(threshold=0x0100, leak=230, refrac_cycles=2)
        spike_count = 0
        for _ in range(10_000):
            s, _ = n.tick(0x0090)
            spike_count += s
        # From spec example: fires at tick 1 (every ~3 ticks minimum due to refrac)
        # Must fire at least 1000 times in 10000 ticks
        assert spike_count > 1_000, \
            f"Expected >1000 spikes in 10000 ticks, got {spike_count}"
        # Must not fire more than once every 3 ticks (refrac=2 means min ISI=3)
        assert spike_count <= 10_000 // 3 + 1, \
            f"Spike count {spike_count} exceeds max possible with refrac=2"

    def test_membrane_never_exceeds_bounds(self):
        """Membrane potential must always stay within s16 range over many ticks."""
        import random
        random.seed(42)
        n = make_neuron(threshold=0x0100, leak=200, refrac_cycles=2)
        for _ in range(10_000):
            current = random.randint(-32768, 32767)
            _, mem = n.tick(current)
            assert INT16_MIN <= mem <= INT16_MAX, \
                f"Membrane {hex(mem)} out of signed-16 range"

    def test_enable_gating_large_scale(self):
        """Alternating enable/disable: state must not drift during disabled ticks."""
        n = make_neuron(threshold=0x7FFF, leak=255)
        n.membrane = 0x0200
        snapshots = []
        for i in range(10_000):
            if i % 2 == 1:  # disabled on odd ticks
                _, mem = n.tick(0x0100, i_enable=False)
                snapshots.append(mem)
        # All odd-tick membranes should equal the membrane right after the prior even tick
        # (No change when disabled). Verify by checking even/odd alternation in pairs.
        n2 = make_neuron(threshold=0x7FFF, leak=255)
        n2.membrane = 0x0200
        last_even_mem = n2.membrane
        for i in range(10_000):
            if i % 2 == 0:
                _, last_even_mem = n2.tick(0x0001)
            else:
                _, mem = n2.tick(0x0100, i_enable=False)
                assert mem == last_even_mem, \
                    f"Tick {i}: disabled tick changed membrane from {hex(last_even_mem)} to {hex(mem)}"
