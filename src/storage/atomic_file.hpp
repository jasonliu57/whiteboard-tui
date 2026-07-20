#pragma once

#include <cstdint>
#include <memory>
#include <ostream>
#include <string>

enum class AtomicFileFault {
    None,
    NoSpace,
    FileSync,
    Close,
    Rename,
    DirectorySync,
};

class AtomicFileWriter {
public:
    explicit AtomicFileWriter(
        const std::string& path,
        AtomicFileFault fault = AtomicFileFault::None
    );
    ~AtomicFileWriter();

    AtomicFileWriter(const AtomicFileWriter&) = delete;
    AtomicFileWriter& operator=(const AtomicFileWriter&) = delete;
    AtomicFileWriter(AtomicFileWriter&&) noexcept;
    AtomicFileWriter& operator=(AtomicFileWriter&&) noexcept;

    bool good() const noexcept;
    std::ostream& stream() noexcept;
    int error_number() const noexcept;
    std::string error() const;
    // Returns true only after the file and its directory are synchronized.
    bool commit();
    // A false commit can still have published a complete file if directory
    // synchronization failed. Callers must not report that the old file remains.
    bool published() const noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
