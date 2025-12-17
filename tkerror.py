from tkinter import messagebox
import traceback
from functools import wraps

def show_on_error(function):
    var=None
    @wraps(function)
    def show_error(*args, **kwargs):
        try:
            var = function(*args, **kwargs)
            return var
        except Exception as e:
            print(traceback.format_exc())
            title = e.__class__.__name__
            message = traceback.format_exc(limit=0)
            messagebox.showerror(f"{title}", f"{message}")
            return var
    return show_error
