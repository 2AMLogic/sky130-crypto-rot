// Bench wrapper: ctr_drbg + a private aes_core. Elaboration is chosen by
// define: default is the shipped 16/8-word seed widths with a small reseed
// interval (so RESEED_REQUIRED is reachable); DRBG_CAVP elaborates 6/4 words
// (24-byte entropy||nonce, 16-byte reseed) to replay the published AES-128
// use-df vectors, whose input lengths the shipped width cannot take.
`ifdef DRBG_CAVP
`define TB_INST 6
`define TB_RSD 4
`define TB_INT 65536
`else
`define TB_INST 16
`define TB_RSD 8
`define TB_INT 5
`endif
module tb_drbg (
    input  wire         clk,
    input  wire         zeroize,
    input  wire         cmd_inst,
    input  wire         cmd_reseed,
    input  wire         cmd_gen,
    input  wire [10:0]  gen_bits,
    input  wire [511:0] seed,
    output wire         busy,
    output wire         done,
    output wire [1:0]   err,
    output wire         seeded,
    output wire         reseed_required,
    output wire         blk_valid,
    output wire         blk_last,
    output wire [127:0] blk_data
);
    wire aes_start, aes_busy, aes_done;
    wire [127:0] aes_key, aes_block, aes_out;
    ctr_drbg #(.INST_WORDS(`TB_INST), .RESEED_WORDS(`TB_RSD), .RESEED_INTERVAL(`TB_INT)) u (
        .clk(clk), .zeroize(zeroize), .cmd_inst(cmd_inst), .cmd_reseed(cmd_reseed),
        .cmd_gen(cmd_gen), .gen_bits(gen_bits), .seed(seed[32*((`TB_INST > `TB_RSD) ? `TB_INST : `TB_RSD)-1:0]),
        .busy(busy), .done(done), .err(err), .seeded(seeded), .reseed_required(reseed_required),
        .blk_valid(blk_valid), .blk_last(blk_last), .blk_data(blk_data),
        .aes_start(aes_start), .aes_key(aes_key), .aes_block(aes_block),
        .aes_busy(aes_busy), .aes_done(aes_done), .aes_out(aes_out));
    aes_core a (.clk(clk), .zeroize(zeroize), .start(aes_start), .decrypt(1'b0),
                .block_in(aes_block), .key_in(aes_key),
                .busy(aes_busy), .done(aes_done), .block_out(aes_out));
endmodule
