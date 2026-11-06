//! The road router's search, out of the interpreter.
//!
//! Python works out the ground - the band's costs, the way the real line runs,
//! the frontage density, the buildings, which corners a road may turn on - and
//! sends it here. This runs the same search the interpreter ran: the same
//! states, the same moves, the same estimate, the same queue order. Nothing
//! about the roads changes but the speed.
//!
//! Framing is little-endian throughout: one INIT frame, then one SEARCH frame
//! per link, each answered by one RESULT frame. The Python side is
//! `generator/roadgraph/rustsearch.py`.

use std::cmp::Ordering;
use std::collections::HashMap;
use std::io::{self, BufWriter, Read, Write};

mod rails;

const N: usize = 16;
const INF: f64 = f64::INFINITY;
const DONE: i32 = -1;
const NO_HEADING: i32 = i32::MIN;
const VERSION: i32 = 1;

fn die(msg: &str) -> ! {
    eprintln!("knoxroute: {msg}");
    std::process::exit(2);
}

struct Reader<R: Read> {
    inner: R,
}

impl<R: Read> Reader<R> {
    fn take(&mut self, n: usize) -> Vec<u8> {
        let mut buf = vec![0u8; n];
        if let Err(e) = self.inner.read_exact(&mut buf) {
            die(&format!("short read ({n} bytes): {e}"));
        }
        buf
    }
    fn i32(&mut self) -> i32 {
        i32::from_le_bytes(self.take(4).try_into().unwrap())
    }
    fn i64(&mut self) -> i64 {
        i64::from_le_bytes(self.take(8).try_into().unwrap())
    }
    fn f64(&mut self) -> f64 {
        f64::from_le_bytes(self.take(8).try_into().unwrap())
    }
    fn i32s(&mut self, n: usize) -> Vec<i32> {
        let raw = self.take(4 * n);
        raw.chunks_exact(4).map(|c| i32::from_le_bytes(c.try_into().unwrap())).collect()
    }
    fn f64s(&mut self, n: usize) -> Vec<f64> {
        let raw = self.take(8 * n);
        raw.chunks_exact(8).map(|c| f64::from_le_bytes(c.try_into().unwrap())).collect()
    }
    fn u8s(&mut self, n: usize) -> Vec<u8> {
        self.take(n)
    }
}

#[derive(Clone)]
struct Move {
    pieces: Vec<(i32, i32)>,
    nh: i32,
    nr: i32,
    sign: i32,
    cost: f64,
}

struct Tables {
    step_x: [i32; N],
    step_y: [i32; N],
    span: [i32; N],
    angle: [f64; N],
    length: [f64; N],
    slope: [usize; N],
    slope_cost: [f64; N],
    dir_penalty: [f64; N],
    /// A notch of turn costs beta x this: the search's own beta times it.
    share: f64,
    reverse: f64,
    bounds: Vec<f64>,
    swing: Vec<[u8; N]>,
}

/// The turns leaving each heading: vanilla's sharp ones, and its curves at the
/// two radii a search uses (a road in town turns tighter than one crossing open
/// country). Sent with each search - they depend on the road's width and class.
struct Moves {
    sharp: Vec<Vec<Move>>,
    curved_small: Vec<Vec<Move>>,
    curved_wide: Vec<Vec<Move>>,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
struct State {
    x: i32,
    y: i32,
    hd: i32,
    run: i32,
    last: i32,
}

#[derive(Clone)]
struct Entry {
    f: f64,
    neg: f64,
    tick: u64,
    st: State,
}

// The queue pops what Python's (f, -cost, tick) sorted tuple pops: smallest f
// first, then the deeper (larger cost), then in the order pushed.
impl PartialEq for Entry {
    fn eq(&self, other: &Self) -> bool {
        self.f == other.f && self.neg == other.neg && self.tick == other.tick
    }
}
impl Eq for Entry {}
/// Python's own float comparison: -0.0 and 0.0 are equal (total_cmp would make
/// -0.0 the smaller, and tie-breaks would part).
fn cmp_f(a: f64, b: f64) -> Ordering {
    if a < b {
        Ordering::Less
    } else if b < a {
        Ordering::Greater
    } else {
        Ordering::Equal
    }
}

impl Ord for Entry {
    fn cmp(&self, other: &Self) -> Ordering {
        cmp_f(self.f, other.f)
            .then_with(|| cmp_f(self.neg, other.neg))
            .then_with(|| self.tick.cmp(&other.tick))
    }
}

// The queue: CPython's heappush and heappop written out, so the pops are the
// same as the interpreter's for the same keys - smallest f, then the deeper
// (larger cost), then the order pushed. A total order over the entries makes
// any valid heap pop the same sequence, which is what lets the two searches be
// compared pop for pop.
fn sift_up(h: &mut [Entry], start: usize, mut pos: usize) {
    let item = h[pos].clone();
    while pos > start {
        let parent = (pos - 1) >> 1;
        if item < h[parent] {
            h[pos] = h[parent].clone();
            pos = parent;
        } else {
            break;
        }
    }
    h[pos] = item;
}

fn sift_down(h: &mut [Entry], pos: usize) {
    let end = h.len();
    let start = pos;
    let item = h[pos].clone();
    let mut pos = pos;
    let mut child = 2 * pos + 1;
    while child < end {
        let right = child + 1;
        if right < end && !(h[child] < h[right]) {
            child = right;
        }
        h[pos] = h[child].clone();
        pos = child;
        child = 2 * pos + 1;
    }
    h[pos] = item;
    sift_up(h, start, pos);
}

fn push(h: &mut Vec<Entry>, e: Entry) {
    h.push(e);
    let n = h.len();
    sift_up(h, 0, n - 1);
}

fn pop(h: &mut Vec<Entry>) -> Option<Entry> {
    let last = h.pop()?;
    if h.is_empty() {
        return Some(last);
    }
    let first = std::mem::replace(&mut h[0], last);
    sift_down(h, 0);
    Some(first)
}
impl PartialOrd for Entry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

struct Search {
    w: i32,
    h: i32,
    x0: i32,
    y0: i32,
    weight: Vec<f64>,
    way: Vec<f64>,
    dens: Option<Vec<f64>>,
    occ: Option<Vec<f64>>,
    turnable: Vec<u8>,
    taken: HashMap<u32, i32>,
    run_here: Vec<i32>,
    s: (i32, i32),
    g: (i32, i32),
    me: i32,
    reach: f64,
    run_min: i32,
    cap: i32,
    end_run: i32,
    end_r: i32,
    road_w: f64,
    jog_end: f64,
    stops: Vec<(i32, i32)>,
    end_short: f64,
    h_start: i32,
    h_arrive: i32,
    lean: f64,
    limit: i64,
}

impl Search {
    #[inline]
    fn idx(&self, x: i32, y: i32) -> usize {
        ((y - self.y0) as usize) * (self.w as usize) + ((x - self.x0) as usize)
    }
    #[inline]
    fn inside(&self, x: i32, y: i32) -> bool {
        x >= self.x0 && y >= self.y0 && x < self.x0 + self.w && y < self.y0 + self.h
    }
    #[inline]
    fn key(&self, x: i32, y: i32, hd: i32) -> u64 {
        let cx = (x - self.x0) as u64;
        let cy = (y - self.y0) as u64;
        (cx << 32) | (cy << 16) | ((hd + 1) as u64)
    }
}

fn bearing(dx: f64, dy: f64) -> f64 {
    let a = dy.atan2(dx).to_degrees() % 360.0;
    if a < 0.0 {
        a + 360.0
    } else {
        a
    }
}

fn adiff(a: f64, b: f64) -> f64 {
    let d = (a - b).abs() % 360.0;
    d.min(360.0 - d)
}

fn notches(a: i32, b: i32) -> i32 {
    let n = N as i32;
    (a - b).rem_euclid(n).min((b - a).rem_euclid(n))
}

struct Ctx<'a> {
    t: &'a Tables,
    s: &'a Search,
    reach_short: f64,
    reach_near: f64,
    hcache: HashMap<u64, f64>,
    notch: f64,
}

impl<'a> Ctx<'a> {
    fn h(&mut self, x: i32, y: i32, hd: i32) -> f64 {
        let key = self.s.key(x, y, hd);
        if let Some(v) = self.hcache.get(&key) {
            return *v;
        }
        let dx = (self.s.g.0 - x) as f64;
        let dy = (self.s.g.1 - y) as f64;
        let mut dist = dx.hypot(dy) - self.reach_short;
        if dist < 0.0 {
            dist = 0.0;
        }
        let out = if hd == DONE {
            dist
        } else {
            let mut turns = 0i32;
            if dx.abs().max(dy.abs()) > self.reach_near {
                let a = bearing(dx, dy);
                let on_boundary = self.t.bounds.iter().any(|b| *b == a);
                turns = if on_boundary {
                    (0..N as i32)
                        .filter(|b| adiff(self.t.angle[*b as usize], a) < 90.0)
                        .map(|b| notches(hd, b))
                        .min()
                        .unwrap_or(0)
                } else {
                    let k = self.t.bounds.partition_point(|b| *b <= a);
                    let row = if k == 0 { self.t.bounds.len() - 1 } else { k - 1 };
                    self.t.swing[row][hd as usize] as i32
                };
            }
            if self.s.h_arrive != NO_HEADING {
                turns = turns.max(notches(hd, self.s.h_arrive));
            }
            self.s.lean * (dist + self.notch * turns as f64)
        };
        self.hcache.insert(key, out);
        out
    }

    /// May the road turn here? (Python's may_turn with the worked-out field.)
    fn may_turn(&self, x: i32, y: i32) -> bool {
        if self.s.turnable[self.s.idx(x, y)] != 0 {
            return true;
        }
        let reach = self.s.jog_end.max(self.s.road_w);
        for q in std::iter::once(&self.s.s)
            .chain(std::iter::once(&self.s.g))
            .chain(self.s.stops.iter())
        {
            let d = ((x - q.0) as f64).hypot((y - q.1) as f64);
            if d <= reach {
                return true;
            }
        }
        false
    }
}

/// A popped state, for the equivalence harness: its estimate, its cost, and the
/// state itself.
type Trace = (f64, f64, i32, i32, i32, i32, i32);

fn run(ctx: &mut Ctx, mv: &Moves, trace: &mut Vec<Trace>, trace_n: i32) -> (Option<Vec<(i32, i32)>>, u64) {
    let (t, s) = (ctx.t, ctx.s);
    let heads: Vec<i32> = if s.h_start == NO_HEADING {
        (0..N as i32).collect()
    } else {
        vec![s.h_start]
    };
    let starts: Vec<State> = heads
        .into_iter()
        .map(|hd| State { x: s.s.0, y: s.s.1, hd, run: s.run_min - s.end_run, last: 0 })
        .collect();
    let mut best: HashMap<State, f64> = HashMap::new();
    let mut came: HashMap<State, State> = HashMap::new();
    let mut via: HashMap<State, Vec<(i32, i32)>> = HashMap::new();
    let mut heap: Vec<Entry> = Vec::new();
    let mut tick = 0u64;
    for st in &starts {
        best.insert(*st, 0.0);
        let f = ctx.h(st.x, st.y, st.hd);
        heap.push(Entry { f, neg: -0.0, tick, st: *st });
        tick += 1;
    }
    // Python heapifies its starts (snap._search does the same): a list is not a heap,
    // and one that is never heapified pops whatever happens to sit at the front.
    for i in (0..heap.len() / 2).rev() {
        sift_down(&mut heap, i);
    }
    let mut seen: i64 = 0;
    while let Some(e) = pop(&mut heap) {
        let cost = -e.neg;
        if cost > *best.get(&e.st).unwrap_or(&INF) {
            continue;
        }
        let st = e.st;
        let (x, y, hd, run_n, last) = (st.x, st.y, st.hd, st.run, st.last);
        if trace_n > 0 {
            trace.push((e.f, cost, x, y, hd, run_n, last));
            if trace.len() as i32 >= trace_n {
                return (None, seen as u64);
            }
        }
        if hd == DONE {
            // The same walk Python makes: the corners of a curved move come
            // before the corner the move started from.
            let mut out: Vec<(i32, i32)> = vec![(x, y)];
            let mut node = *came.get(&st).unwrap_or(&st);
            while let Some(prev) = came.get(&node) {
                if let Some(v) = via.get(&node) {
                    for p in v.iter().rev() {
                        out.push(*p);
                    }
                }
                node = *prev;
                out.push((node.x, node.y));
            }
            out.reverse();
            return (Some(out), seen as u64);
        }
        let near_goal = (x - s.g.0).abs().max((y - s.g.1).abs()) as f64 <= s.reach;
        if near_goal
            && (s.h_arrive == NO_HEADING || s.h_arrive == hd)
            && run_n >= s.end_run
            && (x, y) != s.s
        {
            let done = State { x, y, hd: DONE, run: 0, last: 0 };
            let dc = cost + s.end_short * ((x - s.g.0) as f64).hypot((y - s.g.1) as f64);
            if dc < *best.get(&done).unwrap_or(&INF) {
                best.insert(done, dc);
                came.insert(done, st);
                push(&mut heap, Entry { f: dc, neg: -dc, tick, st: done });
                tick += 1;
            }
        }
        seen += 1;
        if s.limit >= 0 && seen > s.limit {
            return (None, seen as u64);
        }
        let need = s.run_here[s.idx(x, y)];
        let mut nrun = run_n + t.span[hd as usize];
        if nrun > s.cap {
            nrun = s.cap;
        }
        let mut moves: Vec<Move> = Vec::with_capacity(12);
        moves.push(Move {
            pieces: vec![(hd, 1)],
            nh: hd,
            nr: nrun,
            sign: if nrun >= s.cap { 0 } else { last },
            cost: 0.0,
        });
        if run_n >= need && ctx.may_turn(x, y) {
            let short = run_n < 2 * need;
            for m in &mv.sharp[hd as usize] {
                let back = if short && last * m.sign < 0 { t.reverse } else { 0.0 };
                moves.push(Move { cost: m.cost + back, ..m.clone() });
            }
            let curved = if need <= s.run_min { &mv.curved_small } else { &mv.curved_wide };
            for m in &curved[hd as usize] {
                let back = if short && last * m.sign < 0 { t.reverse } else { 0.0 };
                moves.push(Move { cost: m.cost + back, ..m.clone() });
            }
        }
        for m in &moves {
            let (mut cx, mut cy) = (x, y);
            let mut nc = cost + m.cost;
            let mut corners: Vec<(i32, i32)> = Vec::new();
            let mut ok = true;
            'pieces: for (sh, count) in &m.pieces {
                let (dx, dy) = (t.step_x[*sh as usize], t.step_y[*sh as usize]);
                let ang = t.angle[*sh as usize];
                let slope = t.slope[*sh as usize];
                for _ in 0..*count {
                    cx += dx;
                    cy += dy;
                    if !s.inside(cx, cy) {
                        ok = false;
                        break 'pieces;
                    }
                    let i = s.idx(cx, cy);
                    let wgt = s.weight[i];
                    if wgt == INF {
                        ok = false;
                        break 'pieces;
                    }
                    let mut d = (ang - s.way[i]) % 360.0;
                    if d < 0.0 {
                        d += 360.0;
                    }
                    if d > 101.25 && 360.0 - d > 101.25 {
                        ok = false;
                        break 'pieces;
                    }
                    if let Some(owner) = s.taken.get(&(i as u32)) {
                        let ends = ((cx - s.s.0).abs() + (cy - s.s.1).abs())
                            .min((cx - s.g.0).abs() + (cy - s.g.1).abs());
                        if *owner != s.me && ends > s.end_r {
                            ok = false;
                            break 'pieces;
                        }
                    }
                    nc += t.length[*sh as usize] * t.slope_cost[slope] * wgt;
                    if let Some(dens) = &s.dens {
                        nc += t.length[*sh as usize] * dens[i] * t.dir_penalty[slope];
                    }
                    if let Some(occ) = &s.occ {
                        nc += t.length[*sh as usize] * occ[i];
                    }
                    corners.push((cx, cy));
                }
            }
            if !ok {
                continue;
            }
            let ns = State { x: cx, y: cy, hd: m.nh, run: m.nr, last: m.sign };
            if nc < *best.get(&ns).unwrap_or(&INF) {
                best.insert(ns, nc);
                came.insert(ns, st);
                if corners.len() > 1 {
                    let mut keep = corners;
                    keep.pop();
                    via.insert(ns, keep);
                } else {
                    via.remove(&ns);
                }
                let f = nc + ctx.h(cx, cy, m.nh);
                push(&mut heap, Entry { f, neg: -nc, tick, st: ns });
                tick += 1;
            }
        }
    }
    (None, seen as u64)
}

fn read_moves(r: &mut Reader<impl Read>) -> Vec<Move> {
    let n = r.i32().max(0);
    let mut out = Vec::with_capacity(n as usize);
    for _ in 0..n {
        let np = r.i32().max(0);
        let mut pieces = Vec::with_capacity(np as usize);
        for _ in 0..np {
            pieces.push((r.i32(), r.i32()));
        }
        out.push(Move { pieces, nh: r.i32(), nr: r.i32(), sign: r.i32(), cost: r.f64() });
    }
    out
}

fn read_tables(r: &mut Reader<impl Read>) -> Tables {
    let mut step_x = [0i32; N];
    let mut step_y = [0i32; N];
    let mut angle = [0f64; N];
    let mut length = [0f64; N];
    let mut slope = [0usize; N];
    let mut slope_cost = [0f64; N];
    let mut dir_penalty = [0f64; N];
    let mut span = [0i32; N];
    for k in 0..N {
        step_x[k] = r.i32();
        step_y[k] = r.i32();
        span[k] = step_x[k].abs().max(step_y[k].abs());
        angle[k] = r.f64();
        length[k] = r.f64();
        // The client sends a slope's numbers once per heading; keep them by slope id, which
        // is how the step loop looks them up (several headings share a slope).
        let sl = r.i32().max(0) as usize;
        slope[k] = sl;
        slope_cost[sl] = r.f64();
        dir_penalty[sl] = r.f64();
    }
    let share = r.f64();
    let reverse = r.f64();
    let nb = r.i32().max(0) as usize;
    let bounds: Vec<f64> = r.f64s(nb);
    let mut swing = Vec::with_capacity(nb);
    for _ in 0..nb {
        swing.push(r.u8s(N).try_into().unwrap());
    }
    Tables {
        step_x,
        step_y,
        span,
        angle,
        length,
        slope,
        slope_cost,
        dir_penalty,
        share,
        reverse,
        bounds,
        swing,
    }
}

fn main() {
    if std::env::args().nth(1).as_deref() == Some("--rails") {
        rails::run();
        return;
    }
    let mut r = Reader { inner: io::stdin() };
    if r.take(4) != b"KRTE" {
        die("not a knoxroute stream");
    }
    if r.i32() != VERSION {
        die("protocol version mismatch");
    }
    let tables = read_tables(&mut r);
    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());
    loop {
        let mut head = [0u8; 4];
        if r.inner.read_exact(&mut head).is_err() {
            break; // Python closed the pipe
        }
        let w = r.i32();
        let h = r.i32();
        let (x0, y0) = (r.i32(), r.i32());
        let (sx, sy, gx, gy) = (r.i32(), r.i32(), r.i32(), r.i32());
        let h_start = r.i32();
        let h_arrive = r.i32();
        let (reach, run_min, cap, end_run, end_r) = (r.i32(), r.i32(), r.i32(), r.i32(), r.i32());
        let (road_w, jog_end, me) = (r.i32(), r.i32(), r.i32());
        // The junctions the road is routed through: may_turn counts them as places to
        // turn, as the interpreter's does.
        let n_stops = r.i32().max(0) as usize;
        let mut stops: Vec<(i32, i32)> = Vec::with_capacity(n_stops);
        for _ in 0..n_stops {
            stops.push((r.i32(), r.i32()));
        }
        let end_short = r.f64();
        let lean = r.f64();
        let beta = r.f64();
        let limit = r.i64();
        let trace_n = r.i32();
        let mut mv = Moves {
            sharp: Vec::with_capacity(N),
            curved_small: Vec::with_capacity(N),
            curved_wide: Vec::with_capacity(N),
        };
        for _ in 0..N {
            mv.sharp.push(read_moves(&mut r));
            mv.curved_small.push(read_moves(&mut r));
            mv.curved_wide.push(read_moves(&mut r));
        }
        let has_dens = r.i32() != 0;
        let has_occ = r.i32() != 0;
        let ncells = r.i32().max(0) as usize;
        let idx = r.i32s(ncells);
        let weight_v = r.f64s(ncells);
        let way_v = r.f64s(ncells);
        let dens_v = if has_dens { r.f64s(ncells) } else { Vec::new() };
        let occ_v = if has_occ { r.f64s(ncells) } else { Vec::new() };
        let turn_v = r.u8s(ncells);
        let run_v = r.i32s(ncells);
        let ntaken = r.i32().max(0) as usize;
        let taken_idx = r.i32s(ntaken);
        let taken_owner = r.i32s(ntaken);

        let win = (w * h) as usize;
        let mut weight = vec![INF; win];
        let mut way = vec![0f64; win];
        let mut dens = if has_dens { Some(vec![0f64; win]) } else { None };
        let mut occ = if has_occ { Some(vec![0f64; win]) } else { None };
        let mut turnable = vec![0u8; win];
        let mut run_here = vec![run_min; win];
        for k in 0..ncells {
            let i = idx[k] as usize;
            weight[i] = weight_v[k];
            way[i] = way_v[k];
            run_here[i] = run_v[k];
            turnable[i] = turn_v[k];
            if let Some(d) = dens.as_mut() {
                d[i] = dens_v[k];
            }
            if let Some(o) = occ.as_mut() {
                o[i] = occ_v[k];
            }
        }
        let mut taken: HashMap<u32, i32> = HashMap::with_capacity(ntaken);
        for k in 0..ntaken {
            taken.insert(taken_idx[k] as u32, taken_owner[k]);
        }
        let s = Search {
            w,
            h,
            x0,
            y0,
            weight,
            way,
            dens,
            occ,
            turnable,
            taken,
            run_here,
            s: (sx, sy),
            g: (gx, gy),
            me,
            reach: reach as f64,
            run_min,
            cap,
            end_run,
            end_r,
            road_w: road_w as f64,
            jog_end: jog_end as f64,
            stops,
            end_short,
            h_start,
            h_arrive,
            lean,
            limit,
        };
        let mut ctx = Ctx {
            t: &tables,
            s: &s,
            reach_short: (reach as f64) * std::f64::consts::SQRT_2,
            reach_near: reach as f64 + 2.0,
            hcache: HashMap::new(),
            notch: tables.share * beta,
        };
        let mut trace: Vec<Trace> = Vec::new();
        let (path, states) = run(&mut ctx, &mv, &mut trace, trace_n);
        let mut buf: Vec<u8> = Vec::new();
        if trace_n > 0 {
            buf.extend_from_slice(&2i32.to_le_bytes());
            buf.extend_from_slice(&states.to_le_bytes());
            buf.extend_from_slice(&(trace.len() as i32).to_le_bytes());
            for (f, cost, x, y, hd, run_n, last) in &trace {
                buf.extend_from_slice(&f.to_le_bytes());
                buf.extend_from_slice(&cost.to_le_bytes());
                for v in [x, y, hd, run_n, last] {
                    buf.extend_from_slice(&v.to_le_bytes());
                }
            }
        } else {
            buf.extend_from_slice(&(if path.is_some() { 1i32 } else { 0i32 }).to_le_bytes());
            buf.extend_from_slice(&states.to_le_bytes());
            let n = path.as_ref().map(|p| p.len()).unwrap_or(0) as i32;
            buf.extend_from_slice(&n.to_le_bytes());
            if let Some(p) = &path {
                for (x, y) in p {
                    buf.extend_from_slice(&x.to_le_bytes());
                    buf.extend_from_slice(&y.to_le_bytes());
                }
            }
        }
        if out.write_all(&buf).and_then(|_| out.flush()).is_err() {
            break;
        }
    }
}
