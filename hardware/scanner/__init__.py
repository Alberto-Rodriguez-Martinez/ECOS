"""
XYZR scanner (SE SC-03-00): driver (Scanner.py) and serial simulator.

This is a package so the GUI can import the driver by its full dotted name
(hardware.scanner.Scanner) instead of relying on sys.path order. tools/ also
holds an old, unrelated Scanner.py with a different API; a plain
`from Scanner import Scanner` picks whichever directory comes first.
"""
