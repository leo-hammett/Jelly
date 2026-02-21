# src/lif_neuron.v
// LIF Neuron: Leaky Integrate-and-Fire with configurable threshold, leak, and refractory period.
// All arithmetic uses 16-bit signed fixed-point Q8.8.
// Dynamics evaluated on rising clock edge when i_enable is high.

module lif_neuron #(
    parameter DATA_WIDTH    = 16,
    parameter signed [15:0] THRESHOLD     = 16'sh0100,
    parameter [7:0]  LEAK          = 8'd230,
    parameter signed [15:0] RESET_VAL     = 16'sh0000,
    parameter integer REFRAC_CYCLES = 2
)(
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  i_enable,
    input  wire [DATA_WIDTH-1:0] i_current,
    output reg                   o_spike,
    output reg  [DATA_WIDTH-1:0] o_membrane
);

    // Refractory counter — needs to hold values 0..REFRAC_CYCLES
    localparam REFRAC_WIDTH = (REFRAC_CYCLES <= 1)   ? 1 :
                              (REFRAC_CYCLES <= 3)   ? 2 :
                              (REFRAC_CYCLES <= 7)   ? 3 :
                              (REFRAC_CYCLES <= 15)  ? 4 :
                              (REFRAC_CYCLES <= 31)  ? 5 : 6;

    reg [REFRAC_WIDTH-1:0] refractory_counter;

    // Intermediate wires for combinational computation
    // Product: signed 16-bit * unsigned 8-bit (zero-extended to 9-bit signed) = 25-bit signed
    wire signed [24:0] v_product;
    wire signed [15:0] v_leaked;
    wire signed [16:0] v_new_wide;
    wire signed [15:0] v_new;
    wire               overflow_pos;
    wire               overflow_neg;
    wire signed [15:0] v_new_sat;

    // Leak: (V * LEAK) >>> 8 using at least 24-bit intermediate
    assign v_product  = $signed(o_membrane) * $signed({1'b0, LEAK});
    // Arithmetic right-shift by 8: take bits [23:8] of the 25-bit product
    assign v_leaked   = v_product[23:8];

    // Integrate: saturating signed addition
    assign v_new_wide = $signed({v_leaked[DATA_WIDTH-1],   v_leaked})
                      + $signed({i_current[DATA_WIDTH-1], i_current});
    assign overflow_pos = (~v_new_wide[16]) & (v_new_wide[15]);   // positive overflow
    assign overflow_neg =  (v_new_wide[16]) & (~v_new_wide[15]);  // negative overflow
    assign v_new_sat  = overflow_pos ? 16'sh7FFF :
                        overflow_neg ? 16'sh8000 :
                        v_new_wide[15:0];

    // Fire decision: signed comparison
    wire fire;
    assign fire = ($signed(v_new_sat) > $signed(THRESHOLD));

    always @(posedge clk) begin
        if (!rst_n) begin
            o_membrane         <= RESET_VAL;
            refractory_counter <= {REFRAC_WIDTH{1'b0}};
            o_spike            <= 1'b0;
        end else if (i_enable) begin
            o_spike <= 1'b0;

            if (refractory_counter > 0) begin
                // Refractory: decrement counter, hold membrane at RESET_VAL
                refractory_counter <= refractory_counter - 1'b1;
                o_membrane         <= RESET_VAL;
            end else begin
                if (fire) begin
                    // Fire: spike, reset membrane, load refractory counter
                    o_spike            <= 1'b1;
                    o_membrane         <= RESET_VAL;
                    refractory_counter <= REFRAC_CYCLES[REFRAC_WIDTH-1:0];
                end else begin
                    // No fire: store integrated membrane potential
                    o_spike    <= 1'b0;
                    o_membrane <= v_new_sat;
                end
            end
        end else begin
            // i_enable low: hold all state, deassert spike
            o_spike <= 1'b0;
        end
    end

endmodule
