"""tkerror.py

A small helper module to show exceptions in a Tkinter messagebox.

This version is hardened so that exception handling never throws a
secondary exception (e.g., UnboundLocalError inside the handler).

Exports
-------
show_on_error : decorator
    Wrap a function so that if it raises, a messagebox is shown.

Notes
-----
- Default behavior is GUI-friendly: show the error and return None.
- If you need to propagate exceptions (e.g., during debugging), pass
  re_raise=True when creating the decorator.
"""

from __future__ import annotations

from functools import wraps
import traceback

version_tkerror = 'v0.0.1'

try:
    import tkinter.messagebox as messagebox
except Exception:  # Tk isn't available / not initialized
    messagebox = None


def show_on_error(func=None, *, title: str = "Error", re_raise: bool = False):
    """Decorator to show an exception dialog when the wrapped function fails.

    Parameters
    ----------
    func:
        Function to decorate.
    title:
        Title for the error messagebox.
    re_raise:
        If True, re-raise the exception after attempting to show a dialog.
        If False (default), swallow the exception and return None.
    """

    def _decorator(f):
        @wraps(f)
        def _wrapper(*args, **kwargs):
            # Ensure this local exists even if f() crashes before assignment.
            result = None
            try:
                result = f(*args, **kwargs)
                return result
            except Exception as e:
                # Never allow the exception handler to throw.
                try:
                    msg = f"{type(e).__name__}: {e}"
                    if messagebox is not None:
                        messagebox.showerror(title, msg)
                    else:
                        # Fallback to stderr if messagebox is unavailable.
                        traceback.print_exc()
                except Exception:
                    traceback.print_exc()

                if re_raise:
                    raise
                return None

        return _wrapper

    # Support both @show_on_error and @show_on_error(...)
    if func is not None:
        return _decorator(func)
    return _decorator
