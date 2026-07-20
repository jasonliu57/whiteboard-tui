#include "atomic_file.hpp"

#include <atomic>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <memory>
#include <ostream>
#include <streambuf>
#include <string>
#include <string_view>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

class FileDescriptorBuffer final : public std::streambuf {
public:
    FileDescriptorBuffer()
        : buffer_(std::make_unique_for_overwrite<char[]>(kBufferSize)) {
        setp(buffer_.get(), buffer_.get() + kBufferSize);
    }

    FileDescriptorBuffer(const FileDescriptorBuffer&) = delete;
    FileDescriptorBuffer& operator=(const FileDescriptorBuffer&) = delete;

    void set_descriptor(int descriptor) noexcept {
        descriptor_ = descriptor;
    }

    void release_descriptor() noexcept {
        descriptor_ = -1;
    }

    void release_buffer() noexcept {
        setp(nullptr, nullptr);
        buffer_.reset();
    }

protected:
    int_type overflow(int_type character) override {
        if (buffer_ == nullptr) {
            return traits_type::eof();
        }

        if (!flush_buffer()) {
            return traits_type::eof();
        }

        if (!traits_type::eq_int_type(character, traits_type::eof())) {
            *pptr() = traits_type::to_char_type(character);
            pbump(1);
        }

        return traits_type::not_eof(character);
    }

    int sync() override {
        return buffer_ == nullptr || flush_buffer() ? 0 : -1;
    }

private:
    static constexpr std::size_t kBufferSize = 64 * 1024;

    int descriptor_ = -1;
    std::unique_ptr<char[]> buffer_;

    bool flush_buffer() {
        const std::ptrdiff_t size = pptr() - pbase();
        std::ptrdiff_t written = 0;

        while (written < size) {
            const ssize_t count = ::write(
                descriptor_,
                pbase() + written,
                static_cast<std::size_t>(size - written)
            );

            if (count < 0) {
                if (errno == EINTR) {
                    continue;
                }
                return false;
            }

            if (count == 0) {
                errno = EIO;
                return false;
            }

            written += count;
        }

        pbump(-static_cast<int>(size));
        return true;
    }
};

class AtomicFileWriter::Impl {
public:
    explicit Impl(
        const std::string& path,
        AtomicFileFault fault = AtomicFileFault::None
    ) : output_(&buffer_), fault_(fault) {
        open(path);
    }

    ~Impl() {
        discard();
    }

    bool good() const noexcept {
        return descriptor_ >= 0 && directory_ >= 0;
    }

    std::ostream& stream() noexcept {
        return output_;
    }

    int error_number() const noexcept {
        return error_number_;
    }

    std::string error() const {
        return error_number_ == 0
            ? std::string{}
            : std::string{std::strerror(error_number_)};
    }

    bool commit() {
        if (committed_) {
            return true;
        }

        if (!renamed_) {
            if (!write_and_close()) {
                return false;
            }
            if (fault_ == AtomicFileFault::Rename ||
                ::renameat(directory_, temporary_name_.c_str(),
                           directory_, target_name_.c_str()) != 0) {
                if (fault_ == AtomicFileFault::Rename) {
                    errno = EIO;
                }
                remember_error();
                return false;
            }
            renamed_ = true;
        }

        if (fault_ == AtomicFileFault::DirectorySync || ::fsync(directory_) != 0) {
            if (fault_ == AtomicFileFault::DirectorySync) {
                errno = EIO;
            }
            remember_error();
            return false;
        }
        committed_ = true;
        return true;
    }

    bool published() const noexcept {
        return renamed_;
    }

private:
    static inline std::atomic<unsigned long long> sequence_{0};

    int directory_ = -1;
    int descriptor_ = -1;
    std::string target_name_;
    std::string temporary_name_;
    FileDescriptorBuffer buffer_;
    std::ostream output_;
    AtomicFileFault fault_ = AtomicFileFault::None;
    int error_number_ = 0;
    bool renamed_ = false;
    bool committed_ = false;

    bool write_and_close() {
        if (!good()) {
            return false;
        }

        if (fault_ == AtomicFileFault::NoSpace) {
            errno = ENOSPC;
            remember_error();
            output_.setstate(std::ios::badbit);
            close_descriptor();
            buffer_.release_buffer();
            return false;
        }

        output_.flush();

        if (!output_) {
            remember_error();
            close_descriptor();
            buffer_.release_buffer();
            return false;
        }

        if (
            fault_ == AtomicFileFault::FileSync ||
            ::fsync(descriptor_) != 0
        ) {
            if (fault_ == AtomicFileFault::FileSync) {
                errno = EIO;
            }
            remember_error();
            close_descriptor();
            buffer_.release_buffer();
            return false;
        }

        const bool closed = close_descriptor();
        buffer_.release_buffer();

        if (!closed) {
            return false;
        }

        if (fault_ == AtomicFileFault::Close) {
            errno = EIO;
            remember_error();
            return false;
        }

        return true;
    }

    void open(const std::string& path) {
        const std::filesystem::path target{path};
        const std::filesystem::path filename = target.filename();

        if (
            filename.empty() ||
            filename == "." ||
            filename == ".."
        ) {
            error_number_ = EINVAL;
            output_.setstate(std::ios::badbit);
            return;
        }

        const std::filesystem::path parent = target.has_parent_path()
            ? target.parent_path()
            : std::filesystem::path{"."};
        directory_ = ::open(
            parent.c_str(),
            O_RDONLY | O_DIRECTORY | O_CLOEXEC
        );

        if (directory_ < 0) {
            remember_error();
            output_.setstate(std::ios::badbit);
            return;
        }

        target_name_ = filename.string();

        for (unsigned int attempt = 0; attempt < 128; ++attempt) {
            temporary_name_ = ".";
            temporary_name_.append(target_name_);
            temporary_name_.append(".tmp.");
            temporary_name_.append(std::to_string(::getpid()));
            temporary_name_.push_back('.');
            temporary_name_.append(std::to_string(sequence_.fetch_add(1)));

            descriptor_ = ::openat(
                directory_,
                temporary_name_.c_str(),
                O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW,
                S_IRUSR | S_IWUSR
            );

            if (descriptor_ >= 0) {
                buffer_.set_descriptor(descriptor_);
                return;
            }

            if (errno != EEXIST) {
                break;
            }
        }

        remember_error();
        output_.setstate(std::ios::badbit);
    }

    void remember_error() noexcept {
        if (error_number_ == 0) {
            error_number_ = errno == 0 ? EIO : errno;
        }
    }

    bool close_descriptor() noexcept {
        if (descriptor_ < 0) {
            return true;
        }

        const int descriptor = descriptor_;
        descriptor_ = -1;
        buffer_.release_descriptor();

        if (::close(descriptor) != 0) {
            remember_error();
            return false;
        }

        return true;
    }

    void discard() noexcept {
        close_descriptor();

        if (
            directory_ >= 0 &&
            !temporary_name_.empty() &&
            !renamed_
        ) {
            ::unlinkat(
                directory_,
                temporary_name_.c_str(),
                0
            );
        }

        if (directory_ >= 0) {
            ::close(directory_);
            directory_ = -1;
        }
    }
};

AtomicFileWriter::AtomicFileWriter(
    const std::string& path,
    AtomicFileFault fault
) : impl_(std::make_unique<Impl>(path, fault)) {}

AtomicFileWriter::~AtomicFileWriter() = default;

AtomicFileWriter::AtomicFileWriter(AtomicFileWriter&&) noexcept = default;

AtomicFileWriter& AtomicFileWriter::operator=(
    AtomicFileWriter&&
) noexcept = default;

bool AtomicFileWriter::good() const noexcept {
    return impl_ != nullptr && impl_->good();
}

std::ostream& AtomicFileWriter::stream() noexcept {
    if (impl_ == nullptr) {
        static std::ostream invalid_stream{nullptr};
        return invalid_stream;
    }

    return impl_->stream();
}

int AtomicFileWriter::error_number() const noexcept {
    return impl_ == nullptr ? EINVAL : impl_->error_number();
}

std::string AtomicFileWriter::error() const {
    return impl_ == nullptr
        ? std::string{std::strerror(EINVAL)}
        : impl_->error();
}

bool AtomicFileWriter::commit() {
    return impl_ != nullptr && impl_->commit();
}

bool AtomicFileWriter::published() const noexcept {
    return impl_ != nullptr && impl_->published();
}
