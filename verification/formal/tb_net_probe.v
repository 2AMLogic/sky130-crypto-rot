`timescale 1ns/1ps
// One-shot probe for the netlist binding of OP_GEN (issue #177): read the
// synthesized ctr_drbg's op_q bit pattern after an accepted cmd_inst and after
// an accepted cmd_gen. gen_netlist.py runs this over the flattened netlist
// (pinned yosys flatten + icarus) and binds OP_GEN over the bits synthesis
// kept; a bit it optimized away reads z here and must stay out of the binding,
// because it is an unconstrained net in the formal run.
module tb_net_probe;
    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg zeroize = 1'b1;
    reg cmd_inst = 1'b0;
    reg cmd_gen = 1'b0;
    reg [10:0] gen_bits = 11'd0;
    wire busy, done, seeded, reseed_required, blk_valid, blk_last, aes_start;
    wire [1:0] err;
    wire [127:0] blk_data, aes_key, aes_block;
    reg eng_busy = 1'b0, eng_done = 1'b0;
    always @(posedge clk) begin
        if (zeroize)      begin eng_busy <= 1'b0; eng_done <= 1'b0; end
        else if (aes_start && !eng_busy) begin eng_busy <= 1'b1; eng_done <= 1'b0; end
        else if (eng_busy) begin eng_busy <= 1'b0; eng_done <= 1'b1; end
    end
    ctr_drbg dut (
        .clk(clk), .zeroize(zeroize), .cmd_inst(cmd_inst), .cmd_reseed(1'b0),
        .cmd_gen(cmd_gen), .gen_bits(gen_bits), .seed(512'd0),
        .busy(busy), .done(done), .err(err), .seeded(seeded),
        .reseed_required(reseed_required), .blk_valid(blk_valid),
        .blk_last(blk_last), .blk_data(blk_data), .aes_start(aes_start),
        .aes_key(aes_key), .aes_block(aes_block), .aes_busy(eng_busy),
        .aes_done(eng_done), .aes_out(128'd0));
    integer i;
    initial begin
        repeat (4) @(posedge clk);
        zeroize <= 1'b0;
        @(posedge clk);
        cmd_inst <= 1'b1;
        @(posedge clk);
        cmd_inst <= 1'b0;
        i = 0;
        while (seeded !== 1'b1 && i < 200) begin @(posedge clk); i = i + 1; end
        if (seeded !== 1'b1) begin $display("PROBE_FAIL instantiate did not complete"); $finish; end
        repeat (2) @(posedge clk);
        $display("OP_AFTER_INST=%b", dut.op_q);
        @(posedge clk);
        cmd_gen <= 1'b1; gen_bits <= 11'd128;
        @(posedge clk);
        cmd_gen <= 1'b0;
        repeat (2) @(posedge clk);
        if (busy !== 1'b1) $display("PROBE_FAIL busy=%b err=%b", busy, err);
        else $display("OP_AFTER_GEN=%b", dut.op_q);
        $finish;
    end
endmodule
