# Project: Spiking Neural Network Classifier

## Overview
A 4-input, 4-output spiking neural network in synthesizable Verilog. Input spike patterns propagate through a signed-weight synaptic crossbar into Leaky Integrate-and-Fire (LIF) neurons. A Winner-Take-All circuit selects the dominant output, performing tick-based pattern classification. All arithmetic uses 16-bit signed fixed-point Q8.8. Operation is fully deterministic.

## Functional Requirements

### FR-1: Leaky Integrate-and-Fire Neuron (`lif_neuron`)
Implements a single discrete-time LIF neuron with configurable threshold, leak factor, and refractory period.

**Dynamics** (evaluated on the rising clock edge when `i_enable` is high):

1. **Refractory check**: If `refractory_counter > 0`, decrement the counter, hold membrane at `RESET_VAL`, do not fire. Skip remaining steps.
2. **Leak**: Compute `V_leaked = (V * LEAK) >>> 8` using signed arithmetic on V and unsigned LEAK. The intermediate product must be at least 24 bits wide before the arithmetic right shift to avoid truncation.
3. **Integrate**: Compute `V_new = V_leaked + i_current`. On signed overflow, saturate: clamp to `16'sh7FFF` if positive overflow, `16'sh8000` if negative overflow.
4. **Fire**: If `V_new > THRESHOLD` (signed comparison), assert `o_spike` for one cycle, set membrane to `RESET_VAL`, load `refractory_counter` with `REFRAC_CYCLES`. Otherwise store `V_new` as the new membrane potential.

- Parameters:
  - `DATA_WIDTH = 16` — bit width of membrane potential and current (Q8.8 signed fixed-point)
  - `THRESHOLD = 16'sh0100` — fire threshold (default: +1.0 in Q8.8)
  - `LEAK = 8'd230` — unsigned leak factor (default: 230/256 ≈ 0.898)
  - `RESET_VAL = 16'sh0000` — post-spike membrane reset value
  - `REFRAC_CYCLES = 2` — number of ticks the neuron is unresponsive after firing

- Ports:
  - `clk` — clock input
  - `rst_n` — active-low synchronous reset; resets membrane to `RESET_VAL`, clears refractory counter, deasserts `o_spike`
  - `i_enable` — tick enable; neuron only updates state when this is high
  - `i_current [DATA_WIDTH-1:0]` — signed synaptic input current for this tick
  - `o_spike` — high for one clock cycle when the neuron fires
  - `o_membrane [DATA_WIDTH-1:0]` — current membrane potential (registered)

- Constraints:
  - `o_spike` is a single-cycle pulse, asserted on the same clock edge that membrane resets.
  - When `i_enable` is low, all internal state holds (no leak, no integration, no refractory decrement).
  - Signed overflow saturation is mandatory — wrapping produces incorrect neuron dynamics.

- Example (THRESHOLD=16'sh0100, LEAK=8'd230, REFRAC_CYCLES=2, all values in hex):
  ```
  Tick 0: V=0x0000, i_current=0x0090 → V_leaked=0x0000, V_new=0x0090, no fire  → V=0x0090
  Tick 1: V=0x0090, i_current=0x0090 → V_leaked=0x0081, V_new=0x0111, FIRE     → V=0x0000, refrac=2
  Tick 2: V=0x0000, i_current=0x00FF → refractory (2→1), V held at 0x0000       → no fire
  Tick 3: V=0x0000, i_current=0x00FF → refractory (1→0), V held at 0x0000       → no fire
  Tick 4: V=0x0000, i_current=0x0090 → V_leaked=0x0000, V_new=0x0090, no fire  → V=0x0090
  ```

### FR-2: Synaptic Crossbar (`synaptic_crossbar`)
Implements an N_PRE x N_POST weight matrix. On each tick, computes the weighted sum of active input spikes for every post-synaptic neuron.

**Computation** (registered — output valid one cycle after input valid):

For each post-neuron j in 0..N_POST-1:
  `o_currents[j] = SUM over i in 0..N_PRE-1 of (i_spikes[i] ? sign_extend(weight[i][j]) : 0)`

Each WEIGHT_WIDTH-bit signed weight is sign-extended to DATA_WIDTH bits before accumulation. The accumulator uses DATA_WIDTH + ceil(log2(N_PRE)) bits internally, then saturates the result to fit DATA_WIDTH signed range.

**Weight Configuration Protocol**:
On a rising clock edge when `i_cfg_en` is high, write `i_cfg_weight` into `weight[i_cfg_pre][i_cfg_post]`. Configuration writes may occur at any time; new weights take effect starting the next tick computation.

- Parameters:
  - `N_PRE = 4` — number of pre-synaptic inputs
  - `N_POST = 4` — number of post-synaptic outputs
  - `WEIGHT_WIDTH = 8` — signed weight bit width
  - `DATA_WIDTH = 16` — signed output current bit width (Q8.8)

- Ports:
  - `clk` — clock input
  - `rst_n` — active-low synchronous reset; zeroes all weights and deasserts `o_valid`
  - `i_spikes [N_PRE-1:0]` — input spike vector (may be multi-hot)
  - `i_valid` — asserted for one cycle when `i_spikes` is valid
  - `o_currents [N_POST*DATA_WIDTH-1:0]` — packed output; bits `[j*DATA_WIDTH +: DATA_WIDTH]` hold signed current for post-neuron j
  - `o_valid` — asserted one cycle after `i_valid`, indicating `o_currents` is valid
  - `i_cfg_en` — weight configuration write enable
  - `i_cfg_pre [$clog2(N_PRE)-1:0]` — pre-synaptic index for config write
  - `i_cfg_post [$clog2(N_POST)-1:0]` — post-synaptic index for config write
  - `i_cfg_weight [WEIGHT_WIDTH-1:0]` — signed weight value to store

- Constraints:
  - All 16 weights reset to zero on `rst_n`.
  - `o_valid` is a single-cycle pulse exactly one cycle after `i_valid`.
  - Weight sign-extension and accumulator width must prevent silent overflow.

- Example (all weights set to 8'sh10 = +16 decimal, then i_spikes = 4'b1010):
  ```
  Post-neuron 0: w[1][0]*1 + w[3][0]*1 = 16 + 16 = 32 → o_currents[0] = 16'sh0020
  Post-neuron 1: w[1][1]*1 + w[3][1]*1 = 16 + 16 = 32 → o_currents[1] = 16'sh0020
  Post-neuron 2: w[1][2]*1 + w[3][2]*1 = 16 + 16 = 32 → o_currents[2] = 16'sh0020
  Post-neuron 3: w[1][3]*1 + w[3][3]*1 = 16 + 16 = 32 → o_currents[3] = 16'sh0020
  (spikes[0]=0 and spikes[2]=0, so w[0][j] and w[2][j] don't contribute)
  ```

### FR-3: Winner-Take-All Circuit (`wta_circuit`)
Selects the single winning neuron from a multi-hot spike vector using fixed lowest-index priority.

**Behavior** (purely combinational):

- If `i_spikes == 0`: `o_winner = 0`, `o_valid = 0`.
- If `i_spikes != 0`: `o_winner` is a one-hot vector with only the lowest-set bit of `i_spikes` kept. `o_valid = 1`.

The lowest-set-bit extraction can be computed as `i_spikes & (~i_spikes + 1)` or equivalently `i_spikes & (-i_spikes)`.

- Parameters:
  - `N = 4` — number of neurons

- Ports:
  - `i_spikes [N-1:0]` — raw spike vector from neuron array
  - `o_winner [N-1:0]` — one-hot winner output (zero if no spikes)
  - `o_valid` — high when at least one neuron fired

- Constraints:
  - Purely combinational: no clock, no reset, no registered state.
  - Output is always one-hot or all-zero.
  - Tie-breaking is deterministic: lowest index always wins.

- Example:
  ```
  i_spikes = 4'b0000 → o_winner = 4'b0000, o_valid = 0
  i_spikes = 4'b0100 → o_winner = 4'b0100, o_valid = 1
  i_spikes = 4'b1010 → o_winner = 4'b0010, o_valid = 1   (neuron 1 beats neuron 3)
  i_spikes = 4'b1111 → o_winner = 4'b0001, o_valid = 1   (neuron 0 wins)
  i_spikes = 4'b1100 → o_winner = 4'b0100, o_valid = 1   (neuron 2 beats neuron 3)
  ```

### FR-4: SNN Classifier Top Module (`snn_classifier`)
Integrates the crossbar, LIF neuron array, and WTA circuit into a tick-driven classification pipeline.

**Tick Protocol** (3-state FSM):

1. **IDLE** (state 0): Waits for `i_tick` to go high. On `i_tick`: latch `i_spikes` into an internal register, transition to INTEGRATE.
2. **INTEGRATE** (state 1): Assert `i_valid` to crossbar with latched spikes. Crossbar computes weighted currents. Wait one clock cycle for crossbar `o_valid`. Transition to FIRE.
3. **FIRE** (state 2): Route crossbar output currents to the four LIF neurons, assert their `i_enable` for one cycle. Each neuron performs leak-integrate-fire. Collect the four `o_spike` outputs into a 4-bit vector, feed to WTA. Drive `o_class` with WTA `o_winner`, assert `o_valid` for one cycle. Transition to IDLE.

Total pipeline latency: exactly 2 clock cycles from `i_tick` assertion to `o_valid` assertion.

- Parameters:
  - `N_INPUTS = 4` — number of input axons
  - `N_NEURONS = 4` — number of output neurons
  - `WEIGHT_WIDTH = 8` — signed weight bit width
  - `DATA_WIDTH = 16` — potential/current bit width, Q8.8
  - `THRESHOLD = 16'sh0100` — neuron fire threshold
  - `LEAK = 8'd230` — neuron leak factor
  - `REFRAC_CYCLES = 2` — neuron refractory period

- Ports:
  - `clk` — clock input
  - `rst_n` — active-low synchronous reset; resets FSM to IDLE and all sub-modules
  - `i_tick` — single-cycle pulse to start a new tick (must not be asserted while FSM is not IDLE)
  - `i_spikes [N_INPUTS-1:0]` — input spike pattern for this tick
  - `o_class [N_NEURONS-1:0]` — one-hot classification output from WTA
  - `o_valid` — asserted for one cycle when classification result is ready
  - `o_membranes [N_NEURONS*DATA_WIDTH-1:0]` — packed membrane potentials of all neurons (always driven, useful for waveform debugging)
  - `i_cfg_en` — weight configuration write enable (directly forwarded to crossbar)
  - `i_cfg_pre [$clog2(N_INPUTS)-1:0]` — pre-synaptic index for weight config
  - `i_cfg_post [$clog2(N_NEURONS)-1:0]` — post-synaptic index for weight config
  - `i_cfg_weight [WEIGHT_WIDTH-1:0]` — signed weight value for config

- Constraints:
  - `i_tick` must only be asserted when FSM is in IDLE. Behavior is undefined otherwise.
  - `o_valid` is a single-cycle pulse occurring exactly 2 clock cycles after `i_tick`.
  - `o_membranes` is continuously driven and reflects the current registered state of each neuron's membrane potential.
  - Configuration writes to the crossbar pass through directly and may be performed while the FSM is in any state.
  - On `rst_n`, the FSM returns to IDLE, all neuron membranes reset, all crossbar weights zero, `o_valid` deasserts.

- Example (diagonal weight matrix, THRESHOLD=16'sh0040 = +0.25 in Q8.8):
  ```
  Config: w[0][0]=8'sh40, w[1][1]=8'sh40, w[2][2]=8'sh40, w[3][3]=8'sh40. All others=0.

  Tick 1 (cycle N):   i_tick=1, i_spikes=4'b0001
    Cycle N+1:         crossbar computes: neuron0 current=0x0040, others=0x0000
    Cycle N+2:         neuron0: V=0+0x0040=0x0040, 0x0040 == THRESHOLD but not >, no fire
                       o_class=4'b0000, o_valid=1

  Tick 2 (cycle N+4): i_tick=1, i_spikes=4'b0001
    Cycle N+5:         crossbar computes: neuron0 current=0x0040
    Cycle N+6:         neuron0: V_leaked=(0x0040*230)>>8=0x0039, V_new=0x0039+0x0040=0x0079
                       0x0079 > 0x0040, FIRE → o_class=4'b0001, o_valid=1

  Tick 3 (cycle N+8): i_spikes=4'b0100
    neuron0 is refractory, neuron2 gets current 0x0040 → accumulates over ticks
  ```

## API Specification
```verilog
module lif_neuron #(
    parameter DATA_WIDTH    = 16,
    parameter THRESHOLD     = 16'sh0100,
    parameter LEAK          = 8'd230,
    parameter RESET_VAL     = 16'sh0000,
    parameter REFRAC_CYCLES = 2
)(
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  i_enable,
    input  wire [DATA_WIDTH-1:0] i_current,
    output reg                   o_spike,
    output reg  [DATA_WIDTH-1:0] o_membrane
);
endmodule

module synaptic_crossbar #(
    parameter N_PRE        = 4,
    parameter N_POST       = 4,
    parameter WEIGHT_WIDTH = 8,
    parameter DATA_WIDTH   = 16
)(
    input  wire                          clk,
    input  wire                          rst_n,
    input  wire [N_PRE-1:0]             i_spikes,
    input  wire                          i_valid,
    output reg  [N_POST*DATA_WIDTH-1:0] o_currents,
    output reg                           o_valid,
    input  wire                          i_cfg_en,
    input  wire [$clog2(N_PRE)-1:0]     i_cfg_pre,
    input  wire [$clog2(N_POST)-1:0]    i_cfg_post,
    input  wire [WEIGHT_WIDTH-1:0]      i_cfg_weight
);
endmodule

module wta_circuit #(
    parameter N = 4
)(
    input  wire [N-1:0] i_spikes,
    output wire [N-1:0] o_winner,
    output wire         o_valid
);
endmodule

module snn_classifier #(
    parameter N_INPUTS      = 4,
    parameter N_NEURONS     = 4,
    parameter WEIGHT_WIDTH  = 8,
    parameter DATA_WIDTH    = 16,
    parameter THRESHOLD     = 16'sh0100,
    parameter LEAK          = 8'd230,
    parameter REFRAC_CYCLES = 2
)(
    input  wire                              clk,
    input  wire                              rst_n,
    input  wire                              i_tick,
    input  wire [N_INPUTS-1:0]              i_spikes,
    output wire [N_NEURONS-1:0]             o_class,
    output wire                              o_valid,
    output wire [N_NEURONS*DATA_WIDTH-1:0]  o_membranes,
    input  wire                              i_cfg_en,
    input  wire [$clog2(N_INPUTS)-1:0]      i_cfg_pre,
    input  wire [$clog2(N_NEURONS)-1:0]     i_cfg_post,
    input  wire [WEIGHT_WIDTH-1:0]          i_cfg_weight
);
endmodule
```

## Edge Cases
- **Signed overflow saturation**: Membrane potential or crossbar accumulator exceeds 16-bit signed range; must clamp to 16'sh7FFF / 16'sh8000, never wrap
- **All-zero input spikes**: Crossbar produces zero currents; neurons leak only, membrane decays toward zero each tick
- **All-ones input spikes**: Maximum fan-in current injection; verify saturation if weights are large
- **Negative weights**: Inhibitory connections must produce negative currents that reduce membrane potential
- **Mixed positive/negative weights**: Currents may cancel; net current could be near zero despite active spikes
- **Simultaneous neuron spikes**: Multiple neurons exceed threshold on the same tick; WTA must output exactly one winner (lowest index)
- **Refractory blocking**: Neuron in refractory period receives strong input current; membrane must stay at RESET_VAL and neuron must not fire until refractory expires
- **Zero leak factor (LEAK=0)**: Membrane potential is zeroed by leak every tick; neuron can only fire if a single tick's current alone exceeds threshold
- **Maximum leak factor (LEAK=255)**: Minimal decay; membrane accumulates almost completely across ticks
- **Threshold at zero**: Any positive current after leak causes immediate fire
- **Back-to-back ticks**: Ticks issued at minimum 3-cycle spacing; verify FSM completes cleanly and no state corruption
- **Weight update between ticks**: New weights written via config bus between ticks must take effect on the immediately following tick
- **Reset during processing**: Asserting rst_n while FSM is in INTEGRATE or FIRE must return FSM to IDLE and clear all state
- **No-fire accumulation**: Neuron receives sub-threshold current for many consecutive ticks; membrane should ramp up monotonically (modulo leak) and eventually cross threshold
