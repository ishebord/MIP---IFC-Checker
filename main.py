# main.py
import tkinter as tk
from tkinter import messagebox
from ifc_ids_validator.ui_main import App

if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception as e:
        # на случай ранних ImportError покажем аккуратно
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("Критическая ошибка", str(e))
        raise