//! The rail assembly search. Pillow still supplies the exact corridor raster;
//! queue ordering, ties-to-even sampling and assembly order match rails.py.
use super::{cmp_f, die, Reader};
use std::cmp::Ordering;
use std::collections::{BinaryHeap, HashMap};
use std::io::{self, Write};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
struct State(i32, i32, i32, i32);

#[derive(Clone, Copy)]
struct Action {
    index: i32,
    entry: [i32; 2],
    delta: [i32; 2],
    heading: [i32; 2],
}

#[derive(Clone, Copy)]
struct Entry {
    priority: f64,
    cost: f64,
    state: State,
}
impl PartialEq for Entry {
    fn eq(&self, other: &Self) -> bool {
        self.priority == other.priority && self.cost == other.cost && self.state == other.state
    }
}
impl Eq for Entry {}
impl PartialOrd for Entry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for Entry {
    fn cmp(&self, other: &Self) -> Ordering {
        // BinaryHeap is a max heap; Python pops the smallest (f, cost, state).
        cmp_f(other.priority, self.priority)
            .then_with(|| cmp_f(other.cost, self.cost))
            .then_with(|| other.state.cmp(&self.state))
    }
}

struct Guide {
    x0: i32,
    y0: i32,
    width: usize,
    height: usize,
    pixels: Vec<u8>,
}
impl Guide {
    fn deviation(&self, x: f64, y: f64) -> u8 {
        let px = (x / 2.0).round_ties_even() as i64 - i64::from(self.x0);
        let py = (y / 2.0).round_ties_even() as i64 - i64::from(self.y0);
        if px < 0 || py < 0 || px >= self.width as i64 || py >= self.height as i64 {
            return 255;
        }
        self.pixels[py as usize * self.width + px as usize]
    }
}

type Parent = (State, i32, [i32; 2]);
type Section = (i32, i32, i32);

fn search(
    guide: &Guide,
    actions: &HashMap<[i32; 2], Vec<Action>>,
    start: State,
    target: [f64; 2],
    last: [i32; 2],
    end_radius: f64,
) -> Option<Vec<Section>> {
    let remaining = |s: State| (f64::from(s.0) - target[0]).hypot(f64::from(s.1) - target[1]) / 2.0;
    let mut queue = BinaryHeap::from([Entry {
        priority: remaining(start) * 1.15,
        cost: 0.0,
        state: start,
    }]);
    let mut best: HashMap<State, (f64, Option<Parent>)> = HashMap::from([(start, (0.0, None))]);
    let mut final_state = None;
    while let Some(Entry { cost, state, .. }) = queue.pop() {
        if cost != best[&state].0 {
            continue;
        }
        if state != start && remaining(state) <= end_radius && [state.2, state.3] == last {
            final_state = Some(state);
            break;
        }
        for action in actions.get(&[state.2, state.3]).into_iter().flatten() {
            let (Some(nx), Some(ny)) = (
                state.0.checked_add(action.delta[0]),
                state.1.checked_add(action.delta[1]),
            ) else {
                continue;
            };
            let mut samples = [0u8; 4];
            for (i, t) in [0.25, 0.5, 0.75, 1.0].iter().enumerate() {
                samples[i] = guide.deviation(
                    f64::from(state.0) + f64::from(action.delta[0]) * t,
                    f64::from(state.1) + f64::from(action.delta[1]) * t,
                );
            }
            if samples.contains(&255) {
                continue;
            }
            let step = f64::from(action.delta[0]).hypot(f64::from(action.delta[1])) / 2.0;
            let mut candidate = cost
                + step
                    * (1.0
                        + f64::from(samples.iter().map(|v| u32::from(*v)).sum::<u32>()) / 4.0
                            * 0.08);
            if action.index >= 4 {
                candidate += 2.0;
            }
            let next = State(nx, ny, action.heading[0], action.heading[1]);
            if candidate >= best.get(&next).map_or(f64::INFINITY, |v| v.0) {
                continue;
            }
            best.insert(next, (candidate, Some((state, action.index, action.entry))));
            queue.push(Entry {
                priority: candidate + remaining(next) * 1.15,
                cost: candidate,
                state: next,
            });
        }
    }
    let mut state = final_state?;
    let mut path = Vec::new();
    while state != start {
        let (previous, index, entry) = best[&state].1?;
        // Python // rounds negative tile origins towards minus infinity.
        let x = (i64::from(previous.0) - i64::from(entry[0])).div_euclid(2);
        let y = (i64::from(previous.1) - i64::from(entry[1])).div_euclid(2);
        path.push((i32::try_from(x).ok()?, i32::try_from(y).ok()?, index));
        state = previous;
    }
    path.reverse();
    Some(path)
}

fn heading(value: [i32; 2]) -> bool {
    value.iter().all(|v| (-1..=1).contains(v)) && value != [0, 0]
}

pub fn run() {
    let mut r = Reader { inner: io::stdin() };
    if r.take(4) != b"KRL2" {
        die("not a version 2 rail stream");
    }
    let (x0, y0, width, height) = (r.i32(), r.i32(), r.i32(), r.i32());
    let size = usize::try_from(width)
        .ok()
        .zip(usize::try_from(height).ok())
        .and_then(|(w, h)| w.checked_mul(h));
    let Some(size) = size.filter(|n| *n > 0 && *n <= 512 * 1024 * 1024) else {
        die("invalid rail raster size");
    };
    let start = State(r.i32(), r.i32(), r.i32(), r.i32());
    let target = [r.f64(), r.f64()];
    let end_radius = r.f64();
    let last = [r.i32(), r.i32()];
    if !heading([start.2, start.3])
        || !heading(last)
        || target.iter().any(|v| !v.is_finite())
        || !end_radius.is_finite()
        || end_radius <= 0.0
        || end_radius > 2.0
    {
        die("invalid rail endpoint");
    }
    let count = r.i32();
    if !(1..=1024).contains(&count) {
        die("invalid rail assembly count");
    }
    let mut actions: HashMap<[i32; 2], Vec<Action>> = HashMap::new();
    for index in 0..count {
        let entry = [r.i32(), r.i32()];
        let exit = [r.i32(), r.i32()];
        let incoming = [r.i32(), r.i32()];
        let outgoing = [r.i32(), r.i32()];
        if !heading(incoming)
            || !heading(outgoing)
            || entry
                .iter()
                .chain(&exit)
                .any(|v| !(-4096..=4096).contains(v))
            || entry == exit
        {
            die("invalid rail assembly");
        }
        let delta = [exit[0] - entry[0], exit[1] - entry[1]];
        actions.entry(incoming).or_default().push(Action {
            index,
            entry,
            delta,
            heading: outgoing,
        });
        actions
            .entry([-outgoing[0], -outgoing[1]])
            .or_default()
            .push(Action {
                index,
                entry: exit,
                delta: [-delta[0], -delta[1]],
                heading: [-incoming[0], -incoming[1]],
            });
    }
    let guide = Guide {
        x0,
        y0,
        width: width as usize,
        height: height as usize,
        pixels: r.u8s(size),
    };
    let path = search(&guide, &actions, start, target, last, end_radius);
    let stdout = io::stdout();
    let mut out = io::BufWriter::new(stdout.lock());
    out.write_all(b"KRL2").unwrap();
    out.write_all(&path.as_ref().map_or(-1, |p| p.len() as i32).to_le_bytes())
        .unwrap();
    if let Some(path) = path {
        for (x, y, index) in path {
            for v in [x, y, index] {
                out.write_all(&v.to_le_bytes()).unwrap();
            }
        }
    }
    out.flush().unwrap();
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn heap_matches_python_tuple_order() {
        let a = Entry {
            priority: 3.0,
            cost: 2.0,
            state: State(1, 2, 1, 0),
        };
        let b = Entry {
            priority: 3.0,
            cost: 2.0,
            state: State(2, 2, 1, 0),
        };
        let c = Entry {
            priority: 3.0,
            cost: 1.0,
            ..a
        };
        let mut heap = BinaryHeap::from([b, a, c]);
        assert_eq!(heap.pop().unwrap().cost, 1.0);
        assert_eq!(heap.pop().unwrap().state, a.state);
        assert_eq!(heap.pop().unwrap().state, b.state);
    }
    #[test]
    fn samples_round_half_to_even_including_negative_coordinates() {
        let guide = Guide {
            x0: -2,
            y0: 0,
            width: 5,
            height: 1,
            pixels: vec![10, 20, 30, 40, 50],
        };
        assert_eq!(guide.deviation(-1.0, 0.0), 30);
        assert_eq!(guide.deviation(-3.0, 0.0), 10);
        assert_eq!(guide.deviation(3.0, 0.0), 50);
        assert_eq!(guide.deviation(20.0, 0.0), 255);
    }
    #[test]
    fn no_path_and_negative_tile_origin() {
        let start = State(-1, 2, 1, 0);
        let actions = HashMap::from([(
            [1, 0],
            vec![Action {
                index: 0,
                entry: [-1, 2],
                delta: [6, 0],
                heading: [1, 0],
            }],
        )]);
        let mut guide = Guide {
            x0: -2,
            y0: 0,
            width: 9,
            height: 4,
            pixels: vec![0; 36],
        };
        assert_eq!(
            search(&guide, &actions, start, [11.0, 2.0], [1, 0], 1.5),
            Some(vec![(0, 0, 0), (3, 0, 0)])
        );
        guide.pixels.fill(255);
        assert!(search(&guide, &actions, start, [11.0, 2.0], [1, 0], 1.5).is_none());
    }
    #[test]
    fn fractional_endpoints_need_the_port_rounding_radius() {
        let guide = Guide {
            x0: -2,
            y0: 0,
            width: 9,
            height: 4,
            pixels: vec![0; 36],
        };
        let actions = HashMap::from([(
            [1, 0],
            vec![Action {
                index: 0,
                entry: [-1, 2],
                delta: [6, 0],
                heading: [1, 0],
            }],
        )]);
        let start = State(-1, 0, 1, 0);
        assert!(search(&guide, &actions, start, [8.0, 0.2], [1, 0], 1.5).is_none());
        assert_eq!(
            search(
                &guide,
                &actions,
                start,
                [8.0, 0.2],
                [1, 0],
                2.5_f64.sqrt() + 1e-9
            ),
            Some(vec![(0, -1, 0)])
        );
    }
}
