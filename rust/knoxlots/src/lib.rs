//! Reading and writing Project Zomboid lot files.
//!
//! Written from the files themselves: the layouts below were worked out by
//! reading real `.lotheader`, `.lotpack` and `chunkdata_*.bin` files and
//! checking that every file in a compiled map parses to its exact end and
//! writes back byte for byte. No source code of any map editor was used.
//! Where a field's meaning is not known yet it is named for where it is
//! (`field_a`) and kept as it was read.

pub mod bmp;
pub mod cell;
pub mod chunkdata;
pub mod compile;
pub mod header;
pub mod kcell;
pub mod pack;
pub mod spawn;

/// A cursor over bytes that reports what went wrong and where.
pub struct Reader<'a> {
    data: &'a [u8],
    pub pos: usize,
}

impl<'a> Reader<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Reader { data, pos: 0 }
    }

    pub fn left(&self) -> usize {
        self.data.len() - self.pos
    }

    pub fn bytes(&mut self, n: usize) -> Result<&'a [u8], String> {
        if n > self.left() {
            return Err(format!("wanted {n} bytes at {}, {} left", self.pos, self.left()));
        }
        let s = &self.data[self.pos..self.pos + n];
        self.pos += n;
        Ok(s)
    }

    pub fn u32(&mut self) -> Result<u32, String> {
        let b = self.bytes(4)?;
        Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }

    pub fn u64(&mut self) -> Result<u64, String> {
        let b = self.bytes(8)?;
        let mut a = [0u8; 8];
        a.copy_from_slice(b);
        Ok(u64::from_le_bytes(a))
    }

    /// Text up to a newline, as the files store names.
    pub fn line(&mut self) -> Result<String, String> {
        let rest = &self.data[self.pos..];
        let end = rest.iter().position(|&b| b == b'\n').ok_or("a name has no end")?;
        let s = String::from_utf8(rest[..end].to_vec()).map_err(|_| "a name is not text")?;
        self.pos += end + 1;
        Ok(s)
    }
}

pub(crate) fn put_u32(out: &mut Vec<u8>, v: u32) {
    out.extend_from_slice(&v.to_le_bytes());
}
