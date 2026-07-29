// Decompress one Granny Oodle1 section. Public domain, like liboodle itself.
//
// Usage: oodle1_cli <in_blob> <out_file> <memSize> <stop0> <stop1>
//
// The reference demo (ref/demo/Granny.cpp) only accepts Granny v6 files and
// bails on any file with marshal headers - EVE ships v7 with marshal headers,
// so the container is parsed in Python (granny.py) and only the raw section
// payload is handed here.
//
// Framing, per ref/demo/Granny.cpp: a section holds up to three Oodle1 streams.
// All three 12-byte stream headers sit at the FRONT of the payload (offsets
// 0/12/24) and the single shared bitstream begins at offset 36. The
// decompressor is re-initialised per stream but the bitstream runs continuously.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>
#include <oodle/Oodle1.h>

int main(int argc, char **argv) {
    if (argc != 6) {
        std::fprintf(stderr, "usage: %s <in> <out> <memSize> <stop0> <stop1>\n", argv[0]);
        return 2;
    }
    const char *inPath = argv[1], *outPath = argv[2];
    const size_t memSize = std::strtoull(argv[3], nullptr, 10);
    const size_t stop0 = std::strtoull(argv[4], nullptr, 10);
    const size_t stop1 = std::strtoull(argv[5], nullptr, 10);

    std::FILE *f = std::fopen(inPath, "rb");
    if (!f) { std::fprintf(stderr, "cannot open %s\n", inPath); return 1; }
    std::fseek(f, 0, SEEK_END);
    const long len = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);
    // The bitstream refills its 32-bit register ahead of the symbols it emits,
    // so it can read well past the last byte it actually needs. 64 bytes of
    // slack was enough for small single-stream sections but faulted on large
    // multi-stream ones (0xC0000005); give it a whole page.
    std::vector<uint8_t> in(static_cast<size_t>(len) + 4096, 0u);
    if (std::fread(in.data(), 1, static_cast<size_t>(len), f) != static_cast<size_t>(len)) {
        std::fprintf(stderr, "short read on %s\n", inPath); std::fclose(f); return 1;
    }
    std::fclose(f);

    if (len < 36) { std::fprintf(stderr, "payload too small for 3 stream headers\n"); return 1; }

    // A final LZ copy can overshoot the stream boundary it was aiming at, so
    // keep headroom past memSize; only memSize bytes are ever written out.
    std::vector<uint8_t> out(memSize + 65536, 0u);
    const uint32_t *headerPtr = reinterpret_cast<const uint32_t *>(in.data());
    Oodle::Oodle1Bitstream bs(in.data() + 36);
    const size_t streamEnds[3] = { stop0, stop1, memSize };

    size_t outputOffset = 0u;
    for (int streamIdx = 0; streamIdx < 3; streamIdx++) {
        if (outputOffset >= memSize) break;
        std::fprintf(stderr, "stream %d: constructing (out=%zu target=%zu)\n",
                     streamIdx, outputOffset, streamEnds[streamIdx]);
        std::fflush(stderr);
        // heap, not stack: 327 decoders each holding three std::vectors
        auto decomp = std::make_unique<Oodle::Oodle1Decompressor>(bs);
        std::fprintf(stderr, "stream %d: constructed, initialising\n", streamIdx);
        std::fflush(stderr);
        decomp->Initialize(headerPtr);
        headerPtr += 3;
        std::fprintf(stderr, "stream %d: initialised, decoding\n", streamIdx);
        std::fflush(stderr);
        size_t guard = 0u;
        while (outputOffset < streamEnds[streamIdx]) {
            outputOffset += decomp->Decompress(&out[outputOffset]);
            if (++guard > memSize + 16u) {   // emitted nothing / ran away
                std::fprintf(stderr, "stream %d stalled at %zu/%zu\n",
                             streamIdx, outputOffset, streamEnds[streamIdx]);
                return 1;
            }
        }
    }

    if (outputOffset != memSize) {
        std::fprintf(stderr, "produced %zu bytes, expected %zu\n", outputOffset, memSize);
        return 1;
    }
    std::FILE *g = std::fopen(outPath, "wb");
    if (!g) { std::fprintf(stderr, "cannot write %s\n", outPath); return 1; }
    std::fwrite(out.data(), 1, memSize, g);
    std::fclose(g);
    std::fprintf(stderr, "ok: %ld -> %zu bytes\n", len, memSize);
    return 0;
}
