# main.py
import sys
import multiprocessing


def main():
    if "--game" in sys.argv:
        from ifc_ids_validator.game import Game
        Game().run()
        return

    import tkinter as tk
    from tkinter import messagebox
    from ifc_ids_validator.ui_main import App

    try:
        App().mainloop()
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Критическая ошибка", str(e))
        raise


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
