//! knoxlots: work with Project Zomboid lot files.
//!
//!     knoxlots verify <lots folder>          read every file, write it back, compare bytes
//!     knoxlots rebuild <lots folder>         also rebuild each cell's pack and tile table
//!                                            from a plain grid of squares and compare
//!     knoxlots blank-chunkdata <in> <out>    copy a lots folder with every chunkdata blank
//!     knoxlots export <lots> <src> [--keep-zombie]   cell sources made from existing lot files
//!     knoxlots compile <src> <out> [--threads N]     lot files made from cell sources
//!     knoxlots compare <a> <b>               same .lotheader and .lotpack files in both folders?
//!
//! Exit status 0 when everything matched, 1 when something did not, 2 on bad usage.

use knoxlots::cell::Cell;
use knoxlots::chunkdata::ChunkData;
use knoxlots::header::Header;
use knoxlots::compile::{compile_cell, export_cell, Manifest};
use knoxlots::kcell::KCell;
use knoxlots::pack::Pack;
use std::{env, fs, path::Path, path::PathBuf, process::ExitCode};

#[derive(Default)]
struct Tally {
    files: usize,
    same: usize,
    failures: Vec<String>,
}

impl Tally {
    fn note(&mut self, name: &str, ok: Result<bool, String>) {
        self.files += 1;
        match ok {
            Ok(true) => self.same += 1,
            Ok(false) => self.failures.push(format!("{name}: written back different")),
            Err(e) => self.failures.push(format!("{name}: {e}")),
        }
    }
}

fn files(dir: &str) -> Result<Vec<PathBuf>, String> {
    let mut v: Vec<PathBuf> = fs::read_dir(dir)
        .map_err(|e| format!("{dir}: {e}"))?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .collect();
    v.sort();
    Ok(v)
}

fn name_of(p: &Path) -> String {
    p.file_name().and_then(|n| n.to_str()).unwrap_or("").to_string()
}

/// Read a cell's header and pack, build the cell, and write them out again.
fn rebuild(head_bytes: &[u8], pack_bytes: &[u8]) -> Result<(bool, bool), String> {
    let h = Header::parse(head_bytes)?;
    let p = Pack::parse(pack_bytes)?;
    let levels = (h.max_z - h.min_z + 1) as usize;
    let cell = Cell::from_pack(&h.tiles, &p, levels)?;
    let (table, pack) = cell.to_pack();
    let mut h2 = h.clone();
    h2.tiles = table;
    Ok((pack.write() == pack_bytes, h2.write() == head_bytes))
}

fn verify(dir: &str, deep: bool) -> ExitCode {
    let entries = match files(dir) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    let (mut heads, mut packs, mut datas, mut cells) =
        (Tally::default(), Tally::default(), Tally::default(), Tally::default());
    for path in &entries {
        let name = name_of(path);
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        let Ok(bytes) = fs::read(path) else {
            eprintln!("{name}: could not be read");
            continue;
        };
        match ext {
            "lotheader" => {
                heads.note(&name, Header::parse(&bytes).map(|h| h.write() == bytes));
                if deep {
                    let pack_path = path.with_file_name(format!("world_{}.lotpack", name.trim_end_matches(".lotheader")));
                    match fs::read(&pack_path) {
                        Ok(pb) => match rebuild(&bytes, &pb) {
                            Ok((p, h)) => cells.note(&name, Ok(p && h)),
                            Err(e) => cells.note(&name, Err(e)),
                        },
                        Err(_) => cells.note(&name, Err("its lotpack is missing".into())),
                    }
                }
            }
            "lotpack" => packs.note(&name, Pack::parse(&bytes).map(|p| p.write() == bytes)),
            "bin" if name.starts_with("chunkdata_") => {
                datas.note(&name, ChunkData::parse(&bytes).map(|c| c.write() == bytes))
            }
            _ => {}
        }
    }
    let mut bad = heads.files == 0;
    let mut rows = vec![("lotheader", &heads), ("lotpack", &packs), ("chunkdata", &datas)];
    if deep {
        rows.push(("cell rebuilt from squares", &cells));
    }
    for (what, t) in rows {
        println!("{what:26} {} of {} identical", t.same, t.files);
        for f in t.failures.iter().take(3) {
            println!("    {f}");
        }
        bad |= !t.failures.is_empty();
    }
    if bad {
        ExitCode::FAILURE
    } else {
        ExitCode::SUCCESS
    }
}

fn blank(input: &str, output: &str) -> ExitCode {
    let entries = match files(input) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    if let Err(e) = fs::create_dir_all(output) {
        eprintln!("{output}: {e}");
        return ExitCode::from(2);
    }
    let blank = ChunkData { head: [0, 1], grid: vec![0; 1024], blocks: vec![] }.write();
    let (mut copied, mut blanked) = (0, 0);
    for path in entries.iter().filter(|p| p.is_file()) {
        let name = name_of(path);
        let dest = Path::new(output).join(&name);
        let res = if name.starts_with("chunkdata_") && name.ends_with(".bin") {
            blanked += 1;
            fs::write(&dest, &blank)
        } else {
            copied += 1;
            fs::copy(path, &dest).map(|_| ())
        };
        if let Err(e) = res {
            eprintln!("{name}: {e}");
            return ExitCode::FAILURE;
        }
    }
    println!("{copied} files copied, {blanked} chunkdata files made blank, into {output}");
    ExitCode::SUCCESS
}

fn cell_of(name: &str, prefix: &str, suffix: &str) -> Option<(u32, u32)> {
    let rest = name.strip_prefix(prefix)?.strip_suffix(suffix)?;
    let (x, y) = rest.split_once('_')?;
    Some((x.parse().ok()?, y.parse().ok()?))
}

fn export(lots: &str, src: &str, keep_zombie: bool) -> ExitCode {
    let entries = match files(lots) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    if let Err(e) = fs::create_dir_all(src) {
        eprintln!("{src}: {e}");
        return ExitCode::from(2);
    }
    let (mut n, mut failed) = (0, 0);
    let mut field = (8, 8);
    for path in &entries {
        let name = name_of(path);
        let Some((x, y)) = cell_of(&name, "", ".lotheader") else { continue };
        let result = (|| -> Result<(), String> {
            let h = Header::parse(&fs::read(path).map_err(|e| e.to_string())?)?;
            field = (h.field_a, h.field_b);
            let pack_path = path.with_file_name(format!("world_{x}_{y}.lotpack"));
            let p = Pack::parse(&fs::read(&pack_path).map_err(|e| format!("{}: {e}", name_of(&pack_path)))?)?;
            let k = export_cell(x, y, &h, &p, keep_zombie)?;
            fs::write(Path::new(src).join(format!("cell_{x}_{y}.kcell")), k.write()?).map_err(|e| e.to_string())
        })();
        match result {
            Ok(()) => n += 1,
            Err(e) => {
                failed += 1;
                eprintln!("{name}: {e}");
            }
        }
    }
    let m = Manifest { origin_x: 21000, field_a: field.0, field_b: field.1, ..Manifest::default() };
    if let Err(e) = fs::write(Path::new(src).join("source.txt"), m.write()) {
        eprintln!("source.txt: {e}");
        return ExitCode::FAILURE;
    }
    let tail = if failed > 0 { format!(", {failed} failed") } else { String::new() };
    println!("{n} cell sources written to {src}{tail}");
    if failed > 0 { ExitCode::FAILURE } else { ExitCode::SUCCESS }
}

fn compile(src: &str, out: &str, threads: usize) -> ExitCode {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let manifest_path = Path::new(src).join("source.txt");
    let manifest = match fs::read_to_string(&manifest_path)
        .map_err(|e| format!("{}: {e}", manifest_path.display()))
        .and_then(|t| Manifest::parse(&t))
    {
        Ok(m) => m,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    let spawn = match &manifest.spawn_map {
        None => None,
        Some(rel) => match fs::read(Path::new(src).join(rel))
            .map_err(|e| format!("{rel}: {e}"))
            .and_then(|b| knoxlots::bmp::read_grey(&b))
        {
            Ok(img) => Some(img),
            Err(e) => {
                eprintln!("spawn map: {e}");
                return ExitCode::from(2);
            }
        },
    };
    let entries = match files(src) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    let cells: Vec<PathBuf> = entries.into_iter().filter(|p| cell_of(&name_of(p), "cell_", ".kcell").is_some()).collect();
    if cells.is_empty() {
        eprintln!("{src}: no cell_<x>_<y>.kcell files");
        return ExitCode::from(2);
    }
    if let Err(e) = fs::create_dir_all(out) {
        eprintln!("{out}: {e}");
        return ExitCode::from(2);
    }
    let done = AtomicUsize::new(0);
    let next = AtomicUsize::new(0);
    let errors = std::sync::Mutex::new(Vec::<String>::new());
    std::thread::scope(|scope| {
        for _ in 0..threads.max(1) {
            scope.spawn(|| loop {
                let i = next.fetch_add(1, Ordering::SeqCst);
                let Some(path) = cells.get(i) else { break };
                let name = name_of(path);
                let (x, y) = cell_of(&name, "cell_", ".kcell").expect("filtered above");
                let res = (|| -> Result<(), String> {
                    let k = KCell::parse(&fs::read(path).map_err(|e| e.to_string())?)?;
                    if (k.cell_x, k.cell_y) != (x, y) {
                        return Err(format!("the file says it is cell {}_{}", k.cell_x, k.cell_y));
                    }
                    let f = compile_cell(&k, &manifest, spawn.as_ref());
                    let o = Path::new(out);
                    fs::write(o.join(format!("{x}_{y}.lotheader")), f.header).map_err(|e| e.to_string())?;
                    fs::write(o.join(format!("world_{x}_{y}.lotpack")), f.pack).map_err(|e| e.to_string())?;
                    fs::write(o.join(format!("chunkdata_{x}_{y}.bin")), f.chunkdata).map_err(|e| e.to_string())
                })();
                match res {
                    Ok(()) => {
                        done.fetch_add(1, Ordering::SeqCst);
                    }
                    Err(e) => errors.lock().unwrap().push(format!("{name}: {e}")),
                }
            });
        }
    });
    let errors = errors.into_inner().unwrap();
    println!("{} of {} cells compiled into {out}", done.load(Ordering::SeqCst), cells.len());
    for e in errors.iter().take(5) {
        eprintln!("  {e}");
    }
    if errors.is_empty() { ExitCode::SUCCESS } else { ExitCode::FAILURE }
}

fn compare(a: &str, b: &str) -> ExitCode {
    let list = |d: &str| -> Result<Vec<String>, String> {
        Ok(files(d)?.iter().map(|p| name_of(p)).filter(|n| n.ends_with(".lotheader") || n.ends_with(".lotpack")).collect())
    };
    let (la, lb) = match (list(a), list(b)) {
        (Ok(x), Ok(y)) => (x, y),
        (Err(e), _) | (_, Err(e)) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    let (mut same, mut different, mut missing) = (0, Vec::new(), 0);
    for n in &la {
        match (fs::read(Path::new(a).join(n)), fs::read(Path::new(b).join(n))) {
            (Ok(x), Ok(y)) if x == y => same += 1,
            (Ok(_), Ok(_)) => different.push(n.clone()),
            _ => missing += 1,
        }
    }
    let extra = lb.iter().filter(|n| !la.contains(n)).count();
    println!("{same} of {} files identical, {} different, {missing} missing from b, {extra} only in b", la.len(), different.len());
    for n in different.iter().take(5) {
        println!("    differs: {n}");
    }
    if different.is_empty() && missing == 0 && extra == 0 && same > 0 { ExitCode::SUCCESS } else { ExitCode::FAILURE }
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    match args.iter().map(String::as_str).collect::<Vec<_>>().as_slice() {
        ["verify", dir] => verify(dir, false),
        ["rebuild", dir] => verify(dir, true),
        ["blank-chunkdata", input, output] => blank(input, output),
        ["export", lots, src] => export(lots, src, false),
        ["export", lots, src, "--keep-zombie"] => export(lots, src, true),
        ["compile", src, out] => compile(src, out, std::thread::available_parallelism().map_or(1, |n| n.get())),
        ["compile", src, out, "--threads", n] => match n.parse() {
            Ok(n) => compile(src, out, n),
            Err(_) => ExitCode::from(2),
        },
        ["compare", a, b] => compare(a, b),
        _ => {
            eprintln!("usage:\n  knoxlots verify <lots folder>\n  knoxlots rebuild <lots folder>\n  knoxlots blank-chunkdata <in> <out>\n  knoxlots export <lots> <src> [--keep-zombie]\n  knoxlots compile <src> <out> [--threads N]\n  knoxlots compare <a> <b>");
            ExitCode::from(2)
        }
    }
}
