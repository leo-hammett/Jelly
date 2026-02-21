# src/wta_circuit.v
// Winner-Take-All Circuit: purely combinational lowest-index priority selection.
// Extracts the lowest-set bit from i_spikes using i_spikes & (~i_spikes + 1).
// Output is one-hot (zero if no spikes), o_valid high when any spike present.

module wta_circuit #(
    parameter N = 4
)(
    input  wire [N-1:0] i_spikes,
    output wire [N-1:0] o_winner,
    output wire         o_valid
);

    // Lowest-set-bit extraction: x & (-x) in two's complement
    // (~i_spikes + 1) == -i_spikes for unsigned N-bit vectors
    assign o_winner = i_spikes & (~i_spikes + {{(N-1){1'b0}}, 1'b1});
    assign o_valid  = |i_spikes;

endmodule
