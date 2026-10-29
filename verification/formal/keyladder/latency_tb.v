// latency_tb.v -- measures the accept-to-done_pulse latency of one root derivation (issue #56).
// n counts clock edges after the one on which cmd_derive is sampled until done_pulse is seen
// at an edge; the record cites it as the depth the longest operation needs (+-1 edge
// convention). Run by run.sh with Icarus; not a property.
module lat;
reg clk=0, rst_n=0; always #5 clk=~clk;
reg derive=0; wire busy, done, err; wire [3:0] ec;
keyladder k(.clk(clk),.rst_n(rst_n),.zeroize(1'b0),.root_key(256'h11),.root_key_valid(1'b1),
 .cmd_derive(derive),.cmd_lock(1'b0),.ld_begin(1'b0),.cmd_slot(2'd1),.cmd_parent_root(1'b1),.cmd_parent(2'd0),
 .cmd_mask(4'd4),.cmd_ctx(256'h22),.ld_valid(1'b0),.ld_data(32'd0),.busy(busy),.done_pulse(done),.err_pulse(err),
 .err_code(ec),.slot_valid(),.slot_locked(),.hmac_req(1'b0),.hmac_slot(2'd0),.hmac_key(),.aes_req(1'b0),.aes_dec(1'b0),.aes_slot(2'd0),.aes_key(),.rel_deny());
integer n=0;
initial begin repeat(4) @(posedge clk); rst_n<=1; @(posedge clk); derive<=1; @(posedge clk); derive<=0;
 while(!done && n<2000) begin @(posedge clk); n=n+1; end
 $display("DERIVE_LATENCY_CYCLES=%0d err=%b", n, err); $finish; end
endmodule
