#pragma once

#include <istream>
#include <ostream>
#include <streambuf>
#include <string>
#include <string_view>

class StringViewStreamBuffer final : public std::streambuf {
public:
    explicit StringViewStreamBuffer(std::string_view input) {
        char* begin = const_cast<char*>(input.data());
        setg(begin, begin, begin + input.size());
    }
};

class StringViewInputStream final : public std::istream {
public:
    explicit StringViewInputStream(std::string_view input)
        : std::istream(&buffer_), buffer_(input) {}

private:
    StringViewStreamBuffer buffer_;
};

class CountingStreamBuffer final : public std::streambuf {
public:
    std::size_t size() const noexcept {
        return size_;
    }

protected:
    int_type overflow(int_type character) override {
        if (!traits_type::eq_int_type(character, traits_type::eof())) {
            ++size_;
        }

        return traits_type::not_eof(character);
    }

    std::streamsize xsputn(const char*, std::streamsize count) override {
        if (count > 0) {
            size_ += static_cast<std::size_t>(count);
        }

        return count;
    }

private:
    std::size_t size_ = 0;
};

class StringAppendStreamBuffer final : public std::streambuf {
public:
    explicit StringAppendStreamBuffer(std::string& output)
        : output_(output) {}

protected:
    int_type overflow(int_type character) override {
        if (!traits_type::eq_int_type(character, traits_type::eof())) {
            output_.push_back(traits_type::to_char_type(character));
        }

        return traits_type::not_eof(character);
    }

    std::streamsize xsputn(
        const char* data,
        std::streamsize count
    ) override {
        if (count > 0) {
            output_.append(data, static_cast<std::size_t>(count));
        }

        return count;
    }

private:
    std::string& output_;
};

class StringAppendOutputStream final : public std::ostream {
public:
    explicit StringAppendOutputStream(std::string& output)
        : std::ostream(&buffer_), buffer_(output) {}

private:
    StringAppendStreamBuffer buffer_;
};
