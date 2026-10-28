use regex::Regex;
use std::{env, process};
fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() == 2 && args[1] == "--version" {
        println!("recipkg regex probe 0.1.0 (regex 1.13.0)");
        return;
    }
    if args.len() != 3 {
        eprintln!("expected PATTERN TEXT");
        process::exit(64);
    }
    match Regex::new(&args[1]) {
        Ok(re) => {
            let pairs: Vec<String> = re
                .find_iter(&args[2])
                .map(|m| format!("[{},{}]", m.start(), m.end()))
                .collect();
            println!("{{\"matches\":[{}]}}", pairs.join(","));
        }
        Err(_) => {
            println!("{{\"error\":\"compile\"}}");
            process::exit(2);
        }
    }
}
