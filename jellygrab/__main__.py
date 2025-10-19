"""Command line entry point for JellyGrab."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .gui import JellyGrabApp


def main() -> None:
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    JellyGrabApp(root)
    root.mainloop()


if __name__ == "__main__":
    from tkinter import ttk

    main()
