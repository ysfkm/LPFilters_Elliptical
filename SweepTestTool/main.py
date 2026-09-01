"""Entry point for the lowpass filter frequency-response tester."""

from gui import FilterSweepApp


def main():
    app = FilterSweepApp()
    app.mainloop()


if __name__ == "__main__":
    main()
