# src/synaptic_crossbar.v
// Synaptic Crossbar: N_PRE x N_POST weight matrix.
// Computes weighted sum of active input spikes for every post-synaptic neuron.
// Output is registered and valid one cycle after i_valid.
// Weights are WEIGHT_WIDTH-bit signed, sign-extended to DATA_WIDTH before accumulation.
// Accumulator uses DATA_WIDTH + clog2(N_PRE) bits to prevent overflow before saturation.

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

    // Accumulator width: DATA_WIDTH + ceil(log2(N_PRE)) = 16 + 2 = 18 for defaults
    localparam ACC_WIDTH = DATA_WIDTH + $clog2(N_PRE) + 1; // +1 for safety

    // Weight memory: N_PRE x N_POST, each WEIGHT_WIDTH-bit signed
    reg signed [WEIGHT_WIDTH-1:0] weights [0:N_PRE-1][0:N_POST-1];

    // Accumulator array (combinational)
    reg signed [ACC_WIDTH-1:0] acc [0:N_POST-1];

    // Saturation bounds as signed ACC_WIDTH constants
    localparam signed [ACC_WIDTH-1:0] SAT_MAX =  {{(ACC_WIDTH-DATA_WIDTH){1'b0}}, 1'b0, {(DATA_WIDTH-1){1'b1}}};
    localparam signed [ACC_WIDTH-1:0] SAT_MIN =  {{(ACC_WIDTH-DATA_WIDTH){1'b1}}, 1'b1, {(DATA_WIDTH-1){1'b0}}};

    integer i, j;

    // Combinational accumulation
    always @(*) begin
        for (j = 0; j < N_POST; j = j + 1) begin
            acc[j] = {ACC_WIDTH{1'b0}};
            for (i = 0; i < N_PRE; i = i + 1) begin
                if (i_spikes[i]) begin
                    // Sign-extend weight from WEIGHT_WIDTH to ACC_WIDTH
                    acc[j] = acc[j] + {{(ACC_WIDTH-WEIGHT_WIDTH){weights[i][j][WEIGHT_WIDTH-1]}}, weights[i][j]};
                end
            end
        end
    end

    // Registered output
    always @(posedge clk) begin
        if (!rst_n) begin
            o_valid    <= 1'b0;
            o_currents <= {(N_POST*DATA_WIDTH){1'b0}};
            for (i = 0; i < N_PRE; i = i + 1)
                for (j = 0; j < N_POST; j = j + 1)
                    weights[i][j] <= {WEIGHT_WIDTH{1'b0}};
        end else begin
            // Weight configuration write (any time)
            if (i_cfg_en)
                weights[i_cfg_pre][i_cfg_post] <= $signed(i_cfg_weight);

            // Pipeline: register output one cycle after i_valid
            o_valid <= i_valid;
            if (i_valid) begin
                for (j = 0; j < N_POST; j = j + 1) begin
                    // Saturating cast from ACC_WIDTH to DATA_WIDTH
                    if ($signed(acc[j]) > $signed(SAT_MAX))
                        o_currents[j*DATA_WIDTH +: DATA_WIDTH] <= {1'b0, {(DATA_WIDTH-1){1'b1}}}; // 7FFF
                    else if ($signed(acc[j]) < $signed(SAT_MIN))
                        o_currents[j*DATA_WIDTH +: DATA_WIDTH] <= {1'b1, {(DATA_WIDTH-1){1'b0}}}; // 8000
                    else
                        o_currents[j*DATA_WIDTH +: DATA_WIDTH] <= acc[j][DATA_WIDTH-1:0];
                end
            end
        end
    end

endmodule
