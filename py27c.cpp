// Compile Python 2.7 source into the .pyc bytecode the EVE client expects,
// by driving the client's OWN python27.dll.
//
// The client's code.ccp holds 12,527 .pyj entries and nothing else - .pyj is
// zlib-compressed Python 2.7 bytecode (magic 62211). There is no source
// fallback, so patching any client module means producing real 2.7 bytecode.
// No Python 2.7 exists on this machine and winget has none, but the client
// ships python27.dll in tq/bin64 - so it can compile its own modules.
//
// Loading python27.dll into a Python 3 process fails ("Module use of
// python27.dll conflicts with this version of Python"), hence this standalone
// host that LoadLibrary's it directly.
//
// Usage: py27c <python27.dll> <in.py> <out.pyc>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <windows.h>

typedef void  (*fn_void)();
typedef void  (*fn_setpath)(char *);
typedef void *(*fn_compile)(const char *, const char *, int);
typedef void *(*fn_marshal)(void *, int);
typedef long long Py_ssize_t_compat;
typedef int   (*fn_asstring)(void *, char **, Py_ssize_t_compat *);

int main(int argc, char **argv) {
    if (argc != 4) {
        std::fprintf(stderr, "usage: %s <python27.dll> <in.py> <out.pyc>\n", argv[0]);
        return 2;
    }
    HMODULE h = LoadLibraryA(argv[1]);
    if (!h) { std::fprintf(stderr, "cannot load %s (err %lu)\n", argv[1], GetLastError()); return 1; }

    auto Py_Initialize = (fn_void)GetProcAddress(h, "Py_Initialize");
    auto Py_Finalize   = (fn_void)GetProcAddress(h, "Py_Finalize");
    auto PyErr_Print   = (fn_void)GetProcAddress(h, "PyErr_Print");
    auto Py_CompileString = (fn_compile)GetProcAddress(h, "Py_CompileString");
    auto PyMarshal_WriteObjectToString =
        (fn_marshal)GetProcAddress(h, "PyMarshal_WriteObjectToString");
    auto PyString_AsStringAndSize =
        (fn_asstring)GetProcAddress(h, "PyString_AsStringAndSize");
    int *noSite = (int *)GetProcAddress(h, "Py_NoSiteFlag");
    int *noUserSite = (int *)GetProcAddress(h, "Py_NoUserSiteDirectory");
    int *ignoreEnv = (int *)GetProcAddress(h, "Py_IgnoreEnvironmentFlag");

    if (!Py_Initialize || !Py_CompileString || !PyMarshal_WriteObjectToString ||
        !PyString_AsStringAndSize) {
        std::fprintf(stderr, "python27.dll is missing a required export\n");
        return 1;
    }
    // The client's stdlib lives inside code.ccp, which we are not loading; skip
    // site/user-site so Py_Initialize does not go hunting for it.
    if (noSite) *noSite = 1;
    if (noUserSite) *noUserSite = 1;
    if (ignoreEnv) *ignoreEnv = 1;

    Py_Initialize();

    std::FILE *f = std::fopen(argv[2], "rb");
    if (!f) { std::fprintf(stderr, "cannot open %s\n", argv[2]); return 1; }
    std::fseek(f, 0, SEEK_END);
    long n = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);
    std::vector<char> src(n + 2, 0);
    if (std::fread(src.data(), 1, n, f) != (size_t)n) { std::fclose(f); return 1; }
    std::fclose(f);
    if (n == 0 || src[n - 1] != '\n') { src[n] = '\n'; }

    const int Py_file_input = 257;
    void *code = Py_CompileString(src.data(), argv[2], Py_file_input);
    if (!code) {
        std::fprintf(stderr, "compile failed:\n");
        if (PyErr_Print) PyErr_Print();
        return 1;
    }
    void *blob = PyMarshal_WriteObjectToString(code, 2);   // marshal version 2
    if (!blob) { std::fprintf(stderr, "marshal failed\n"); return 1; }

    char *bytes = nullptr;
    Py_ssize_t_compat len = 0;
    if (PyString_AsStringAndSize(blob, &bytes, &len) != 0) {
        std::fprintf(stderr, "could not read marshalled bytes\n");
        return 1;
    }

    std::FILE *o = std::fopen(argv[3], "wb");
    if (!o) { std::fprintf(stderr, "cannot write %s\n", argv[3]); return 1; }
    unsigned int magic = 62211 | (('\r' << 16) | ('\n' << 24));  // 03 f3 0d 0a
    unsigned int stamp = 0;
    std::fwrite(&magic, 4, 1, o);
    std::fwrite(&stamp, 4, 1, o);
    std::fwrite(bytes, 1, (size_t)len, o);
    std::fclose(o);
    std::fprintf(stderr, "ok: %ld bytes source -> %lld bytes bytecode\n", n, (long long)len);
    if (Py_Finalize) Py_Finalize();
    return 0;
}
