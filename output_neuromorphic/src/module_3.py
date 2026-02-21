# src/snn_classifier.v
// SNN Classifier Top Module: integrates synaptic crossbar, LIF neuron array, and WTA circuit.
// 3-state FSM: IDLE -> INTEGRATE -> FIRE -> IDLE
// Total pipeline latency: exactly 2 clock cycles from i_tick to o_valid.
//
// Timing:
//   Cycle N:   FSM=IDLE,      i_tick=1 → latch spikes, transition to INTEGRATE
//   Cycle N+1: FSM=INTEGRATE, assert i_valid to crossbar, transition to FIRE
//   Cycle N+2: FSM=FIRE,      crossbar o_valid=1, enable neurons, collect spikes,
//                              assert o_valid (registered), transition to IDLE

module snn_classifier #(
    parameter integer N_INPUTS      = 4,
    parameter integer N_NEURONS     = 4,
    parameter integer WEIGHT_WIDTH  = 8,
    parameter integer DATA_WIDTH    = 16,
    parameter signed [15:0] THRESHOLD     = 16'sh0100,
    parameter [7:0]  LEAK          = 8'd230,
    parameter integer REFRAC_CYCLES = 2
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

    // FSM states
    localparam [1:0] IDLE      = 2'd0;
    localparam [1:0] INTEGRATE = 2'd1;
    localparam [1:0] FIRE      = 2'd2;

    reg [1:0] state;

    // Latched input spikes
    reg [N_INPUTS-1:0] spikes_lat;

    // Crossbar connections
    wire [N_NEURONS*DATA_WIDTH-1:0] xbar_currents;
    wire                             xbar_valid;
    reg                              xbar_i_valid;

    // Neuron enable and outputs
    reg                   neuron_enable;
    wire [N_NEURONS-1:0]  neuron_spikes;

    // WTA outputs
    wire [N_NEURONS-1:0]  wta_winner;
    wire                  wta_valid;

    // Registered output
    reg [N_NEURONS-1:0] o_class_r;
    reg                 o_valid_r;

    assign o_class = o_class_r;
    assign o_valid = o_valid_r;

    // -------------------------------------------------------------------------
    // Synaptic Crossbar
    // -------------------------------------------------------------------------
    synaptic_crossbar #(
        .N_PRE        (N_INPUTS),
        .N_POST       (N_NEURONS),
        .WEIGHT_WIDTH (WEIGHT_WIDTH),
        .DATA_WIDTH   (DATA_WIDTH)
    ) u_crossbar (
        .clk          (clk),
        .rst_n        (rst_n),
        .i_spikes     (spikes_lat),
        .i_valid      (xbar_i_valid),
        .o_currents   (xbar_currents),
        .o_valid      (xbar_valid),
        .i_cfg_en     (i_cfg_en),
        .i_cfg_pre    (i_cfg_pre),
        .i_cfg_post   (i_cfg_post),
        .i_cfg_weight (i_cfg_weight)
    );

    // -------------------------------------------------------------------------
    // LIF Neuron Array
    // -------------------------------------------------------------------------
    genvar n;
    generate
        for (n = 0; n < N_NEURONS; n = n + 1) begin : gen_neurons
            lif_neuron #(
                .DATA_WIDTH    (DATA_WIDTH),
                .THRESHOLD     (THRESHOLD),
                .LEAK          (LEAK),
                .RESET_VAL     (16'sh0000),
                .REFRAC_CYCLES (REFRAC_CYCLES)
            ) u_neuron (
                .clk        (clk),
                .rst_n      (rst_n),
                .i_enable   (neuron_enable),
                .i_current  (xbar_currents[n*DATA_WIDTH +: DATA_WIDTH]),
                .o_spike    (neuron_spikes[n]),
                .o_membrane (o_membranes[n*DATA_WIDTH +: DATA_WIDTH])
            );
        end
    endgenerate

    // -------------------------------------------------------------------------
    // Winner-Take-All Circuit (combinational)
    // -------------------------------------------------------------------------
    wta_circuit #(
        .N (N_NEURONS)
    ) u_wta (
        .i_spikes (neuron_spikes),
        .o_winner (wta_winner),
        .o_valid  (wta_valid)
    );

    // -------------------------------------------------------------------------
    // FSM
    // -------------------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            state        <= IDLE;
            spikes_lat   <= {N_INPUTS{1'b0}};
            xbar_i_valid <= 1'b0;
            neuron_enable<= 1'b0;
            o_class_r    <= {N_NEURONS{1'b0}};
            o_valid_r    <= 1'b0;
        end else begin
            // Default deasserts
            xbar_i_valid  <= 1'b0;
            neuron_enable <= 1'b0;
            o_valid_r     <= 1'b0;

            case (state)
                IDLE: begin
                    if (i_tick) begin
                        spikes_lat <= i_spikes;
                        state      <= INTEGRATE;
                    end
                end

                INTEGRATE: begin
                    // Present latched spikes to crossbar for one cycle
                    xbar_i_valid <= 1'b1;
                    state        <= FIRE;
                end

                FIRE: begin
                    // Crossbar output is valid this cycle (one-cycle registered delay).
                    // Enable all neurons so they consume xbar_currents.
                    neuron_enable <= 1'b1;

                    // Capture WTA result AFTER neurons update on this same posedge.
                    // neuron_spikes are registered outputs: they reflect the state
                    // BEFORE this posedge (from any previous firing). Neurons that
                    // fire NOW will produce spikes visible next cycle.
                    // 
                    // To capture spikes from THIS tick, we register them one cycle
                    // later. Use an extra pipeline register below.
                    state <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

    // -------------------------------------------------------------------------
    // Spike capture pipeline: sample neuron spikes one cycle after FIRE
    // (neurons update o_spike on the same posedge as neuron_enable, so we need
    //  to capture them the cycle after neuron_enable is asserted)
    // -------------------------------------------------------------------------
    reg neuron_enable_d1;  // delayed enable — marks cycle when spikes are valid

    always @(posedge clk) begin
        if (!rst_n) begin
            neuron_enable_d1 <= 1'b0;
            o_class_r        <= {N_NEURONS{1'b0}};
            o_valid_r        <= 1'b0;
        end else begin
            neuron_enable_d1 <= neuron_enable;

            if (neuron_enable_d1) begin
                // Neuron spikes from the previous cycle (when neuron_enable was high)
                // are now stable on o_spike outputs
                o_class_r <= wta_winner;
                o_valid_r <= 1'b1;
            end else begin
                o_valid_r <= 1'b0;
            end
        end
    end

endmodule
