// A stand-in for python27.exe that runs the script inside the EVE client.
//
// The Elysian kit's native loader/exporter/compiler-probe all shell out as
//     python27.exe <worker.py> <task.json> <result.json>
// but the kit's bundled runtime is stdlib-only (Lib, no interpreter), and the
// workers need the client's *Loader.pyd modules anyway. The client exposes
//     exefile.exe /py <script> <args...> /inherit
// so this shim just translates one calling convention into the other.
//
// Point the kit at this binary with --python27 / EvePython27 and everything
// that needs a native loader starts working, including the compiler's
// verification probe (which is what gates every string patch).
//
// Set EVE_EXEFILE to override the client path.
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#include <windows.h>

static std::string quote(const std::string &s) {
    if (s.find_first_of(" \t\"") == std::string::npos) return s;
    std::string out = "\"";
    for (char c : s) {
        if (c == '"') out += '\\';
        out += c;
    }
    out += '"';
    return out;
}

int main(int argc, char **argv) {
    const char *env = std::getenv("EVE_EXEFILE");
    std::string exe = env && *env
        ? env
        : "C:\\EVE-EVEJS\\client\\EVE\\tq\\bin64\\exefile.exe";

    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <script.py> [args...]\n", argv[0]);
        return 2;
    }

    // The kit's callers set PYTHONPATH=bin64 but never PYTHONHOME, and the
    // worker needs a 2.7 stdlib. This shim is installed at
    //     <home>\python27\python.exe
    // with the stdlib beside it at <home>\python27\Lib, so derive both from our
    // own location rather than depending on the caller's environment.
    char self[MAX_PATH] = {0};
    if (GetModuleFileNameA(nullptr, self, MAX_PATH)) {
        std::string dir(self);
        size_t slash = dir.find_last_of("\\/");
        if (slash != std::string::npos) {
            dir = dir.substr(0, slash);
            SetEnvironmentVariableA("PYTHONHOME", dir.c_str());
            std::string lib = dir + "\\Lib";
            const char *existing = std::getenv("PYTHONPATH");
            std::string full = lib + (existing && *existing
                                      ? std::string(";") + existing : "");
            SetEnvironmentVariableA("PYTHONPATH", full.c_str());
        }
    }

    std::string cmd = quote(exe) + " /py";
    for (int i = 1; i < argc; ++i) cmd += " " + quote(argv[i]);
    cmd += " /inherit";

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    std::vector<char> buffer(cmd.begin(), cmd.end());
    buffer.push_back('\0');

    if (!CreateProcessA(nullptr, buffer.data(), nullptr, nullptr, TRUE,
                        0, nullptr, nullptr, &si, &pi)) {
        std::fprintf(stderr, "CreateProcess failed (%lu): %s\n",
                     GetLastError(), cmd.c_str());
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return static_cast<int>(code);
}
