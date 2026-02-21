"""
Behavioral model + tests for FR-3: Winner-Take-All Circuit.

The WTA is purely combinational; tests model it as a pure function.
"""
import pytest


# ---------------------------------------------------------------------------
# Behavioral model (test oracle)
# ---------------------------------------------------------------------------

def wta(i_spikes: int, n: int = 4) -> tuple[int, int]:
    """
    Combinational WTA: returns (o_winner, o_valid).
    o_winner is one-hot lowest-index winner; o_valid=1 iff any spike.
    """
    mask = (1 << n) - 1
    i_spikes &= mask
    if i_spikes == 0:
        return 0, 0
    # Isolate lowest set bit
    winner = i_spikes & (-i_spikes)
    return winner, 1


# ---------------------------------------------------------------------------
# Tier 1 – Basic Functionality
# ---------------------------------------------------------------------------

class TestWTACircuitBasicFunctionality:

    def test_no_spikes_no_winner(self):
        """i_spikes=0 → o_winner=0, o_valid=0."""
        w, v = wta(0b0000)
        assert w == 0b0000, f"No spikes: expected winner=0, got {bin(w)}"
        assert v == 0, f"No spikes: expected valid=0, got {v}"

    def test_single_spike_neuron0(self):
        """Only neuron 0 spikes → o_winner=0b0001, o_valid=1."""
        w, v = wta(0b0001)
        assert w == 0b0001, f"Expected 0b0001, got {bin(w)}"
        assert v == 1, f"Expected valid=1, got {v}"

    def test_single_spike_neuron2(self):
        """Only neuron 2 spikes → o_winner=0b0100, o_valid=1 (spec example)."""
        w, v = wta(0b0100)
        assert w == 0b0100, f"Expected 0b0100, got {bin(w)}"
        assert v == 1, f"Expected valid=1, got {v}"

    def test_two_spikes_lowest_wins(self):
        """Spikes on neurons 1 and 3 → neuron 1 wins (spec example)."""
        w, v = wta(0b1010)
        assert w == 0b0010, f"Expected 0b0010 (neuron 1 wins), got {bin(w)}"
        assert v == 1

    def test_all_spikes_neuron0_wins(self):
        """All four neurons spike → neuron 0 wins (spec example)."""
        w, v = wta(0b1111)
        assert w == 0b0001, f"Expected 0b0001 (neuron 0 always wins), got {bin(w)}"
        assert v == 1

    def test_winner_is_always_one_hot(self):
        """Output must always be one-hot or all-zero — never multi-hot."""
        for spikes in range(1 << 4):
            w, _ = wta(spikes)
            if w != 0:
                assert (w & (w - 1)) == 0, \
                    f"i_spikes={bin(spikes)}: winner {bin(w)} is not one-hot"


# ---------------------------------------------------------------------------
# Tier 2 – Edge Cases
# ---------------------------------------------------------------------------

class TestWTACircuitEdgeCases:

    def test_neuron1_beats_neuron3(self):
        """Spec example: i_spikes=0b1010 → winner=neuron1 (index 1)."""
        w, v = wta(0b1010)
        assert w == 0b0010, f"Expected neuron1 winner=0b0010, got {bin(w)}"
        assert v == 1

    def test_neuron2_beats_neuron3(self):
        """Spec example: i_spikes=0b1100 → winner=neuron2."""
        w, v = wta(0b1100)
        assert w == 0b0100, f"Expected neuron2 winner=0b0100, got {bin(w)}"
        assert v == 1

    def test_single_neuron3(self):
        """Only neuron 3 spikes → o_winner=0b1000."""
        w, v = wta(0b1000)
        assert w == 0b1000, f"Expected 0b1000, got {bin(w)}"
        assert v == 1

    def test_adjacent_neurons_lower_wins(self):
        """Neurons 0 and 1 both spike → neuron 0 wins."""
        w, v = wta(0b0011)
        assert w == 0b0001, f"Expected 0b0001, got {bin(w)}"

    def test_all_neurons_except_0(self):
        """Neurons 1,2,3 spike → neuron 1 wins."""
        w, v = wta(0b1110)
        assert w == 0b0010, f"Expected 0b0010, got {bin(w)}"

    def test_o_valid_false_on_zero(self):
        """o_valid strictly 0 on all-zero input."""
        _, v = wta(0b0000)
        assert v == 0, f"Expected o_valid=0, got {v}"

    def test_o_valid_true_on_any_nonzero(self):
        """o_valid is 1 for every non-zero input (1..15)."""
        for spikes in range(1, 1 << 4):
            _, v = wta(spikes)
            assert v == 1, f"i_spikes={bin(spikes)}: expected o_valid=1, got {v}"

    def test_winner_index_matches_lowest_set_bit(self):
        """o_winner's bit position equals the index of the lowest set bit in i_spikes."""
        for spikes in range(1, 1 << 4):
            w, _ = wta(spikes)
            # Find lowest bit index
            lsb = (spikes & -spikes).bit_length() - 1
            expected = 1 << lsb
            assert w == expected, \
                f"i_spikes={bin(spikes)}: expected winner bit {lsb} (={bin(expected)}), got {bin(w)}"

    def test_combinational_determinism(self):
        """Same input always produces same output (no state dependency)."""
        for spikes in range(1 << 4):
            w1, v1 = wta(spikes)
            w2, v2 = wta(spikes)
            assert w1 == w2 and v1 == v2, \
                f"Non-determinism for i_spikes={bin(spikes)}"

    def test_winner_is_subset_of_input_spikes(self):
        """o_winner must be a subset of i_spikes (winner was actually spiking)."""
        for spikes in range(1 << 4):
            w, _ = wta(spikes)
            assert (w & spikes) == w, \
                f"Winner {bin(w)} not a subset of i_spikes={bin(spikes)}"

    def test_larger_n_8_neurons(self):
        """WTA with N=8 — lowest bit still wins."""
        for spikes in range(1, 1 << 8):
            w, v = wta(spikes, n=8)
            expected = spikes & (-spikes)
            assert w == expected, \
                f"N=8, i_spikes={bin(spikes)}: expected {bin(expected)}, got {bin(w)}"
            assert v == 1


# ---------------------------------------------------------------------------
# Tier 3 – Large-Scale Tests
# ---------------------------------------------------------------------------

class TestWTACircuitLargeScale:

    def test_all_4bit_inputs_exhaustive(self):
        """Exhaustive check of all 16 possible 4-bit inputs."""
        for spikes in range(1 << 4):
            w, v = wta(spikes, n=4)
            if spikes == 0:
                assert w == 0 and v == 0, f"spikes=0: expected (0,0), got ({w},{v})"
            else:
                assert v == 1, f"spikes={bin(spikes)}: expected v=1, got {v}"
                assert w == (spikes & -spikes), \
                    f"spikes={bin(spikes)}: expected {bin(spikes & -spikes)}, got {bin(w)}"

    def test_all_8bit_inputs_exhaustive(self):
        """Exhaustive check of all 256 possible 8-bit inputs with N=8."""
        for spikes in range(1 << 8):
            w, v = wta(spikes, n=8)
            if spikes == 0:
                assert w == 0 and v == 0
            else:
                assert v == 1
                expected = spikes & (-spikes)
                assert w == expected, \
                    f"N=8, spikes={bin(spikes)}: expected {bin(expected)}, got {bin(w)}"

    def test_sequential_single_hot_inputs(self):
        """Feed each one-hot pattern 10000 times; winner must equal input."""
        for neuron in range(4):
            spike = 1 << neuron
            for _ in range(10_000):
                w, v = wta(spike)
                assert w == spike, \
                    f"One-hot neuron {neuron}: expected {bin(spike)}, got {bin(w)}"
                assert v == 1
