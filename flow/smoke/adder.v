// Smoke design for the toolchain bring-up (issue #4): a registered 8-bit
// adder. Not part of the root of trust; it exists only so one pinned
// environment can be shown to run RTL simulation and synthesis end to end.
module adder (
    input  wire       clk,
    input  wire [7:0] a,
    input  wire [7:0] b,
    output reg  [8:0] sum
);
    always @(posedge clk) sum <= {1'b0, a} + {1'b0, b};
endmodule
