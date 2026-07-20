export function createUnicodeProvider({ version, zeroWidth, control, wide }) {
  const contains = (intervals, value) => {
    let first = 0, last = intervals.length;
    while (first < last) {
      const middle = (first + last) >>> 1;
      const [low, high] = intervals[middle];
      if (value < low) last = middle;
      else if (value > high) first = middle + 1;
      else return true;
    }
    return false;
  };
  const wcwidth = value => {
    if (value >= 32 && value <= 126) return 1;
    if (value < 32 || value === 127 || value > 0x10ffff ||
        (value >= 0xd800 && value <= 0xdfff) || contains(control, value)) return 0;
    if (contains(zeroWidth, value)) return 0;
    return contains(wide, value) ? 2 : 1;
  };
  return {
    version, wcwidth,
    // xterm 6 encodes cell width in bits 1..2 and combining continuation in bit 0.
    charProperties(codepoint, preceding) {
      const width = wcwidth(codepoint);
      const previousWidth = (preceding >>> 1) & 3;
      return width === 0 && previousWidth > 0 ? (previousWidth << 1) | 1 : width << 1;
    }
  };
}
