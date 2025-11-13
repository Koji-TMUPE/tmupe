import tkinter as tk
import tkinter.ttk as ttk
import sys
import math

class ScrollableFrame(ttk.Frame):
    OS = sys.platform

    def __init__(self, container, bar_x=True, bar_y=True, hbg='#EEEEEE', ht=0):
        super().__init__(container)

        self._bar_x = bar_x
        self._bar_y = bar_y

        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollable_frame = tk.Frame(self.canvas, highlightbackground=hbg, highlightthickness=ht)
#        self.scrollable_frame = ttk.Frame(self.canvas)

        # 内部フレームをキャンバスに配置
        self.window_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        # --- Scrollbar の素結線（これが最重要） ---
        #   ・Scrollbar -> Canvas は command=canvas.yview/xview
        #   ・Canvas   -> Scrollbar は yscrollcommand/xscrollcommand=scrollbar.set
        if bar_y:
            self.scrollbar_y = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.scrollbar_y.pack(side=tk.RIGHT, fill="y")
            self.canvas.configure(yscrollcommand=self.scrollbar_y.set)
        else:
            self.scrollbar_y = None

        if bar_x:
            self.scrollbar_x = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
            self.scrollbar_x.pack(side=tk.BOTTOM, fill="x")
            self.canvas.configure(xscrollcommand=self.scrollbar_x.set)
        else:
            self.scrollbar_x = None

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- 中身/Canvas サイズ変化時に scrollregion を更新 ---
        self.scrollable_frame.bind("<Configure>", self._on_interior_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # --- ホイール: Canvas/内部フレーム上に入ったら bind_all、離れたら解除 ---
        self.canvas.bind("<Enter>", self._activate_mousewheel)
        self.canvas.bind("<Leave>", self._deactivate_mousewheel)
        self.scrollable_frame.bind("<Enter>", self._activate_mousewheel)
        self.scrollable_frame.bind("<Leave>", self._deactivate_mousewheel)

    # 中身が変わったら scrollregion を「実内容」に更新
    def _on_interior_configure(self, event=None):
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)
        # 横スクロールを使わないときは内部フレームの幅をキャンバス幅に合わせて、横方向の不要なスクロールを防ぐ
        if not self._bar_x:
            c_w = self.canvas.winfo_width()
            # 幅を固定すると、縦方向の比率（つまみ長）も正しく算出されやすい
            self.canvas.itemconfigure(self.window_id, width=c_w)
        # 縦スクロールを使わないときは内部フレームの高さをキャンバス高さに合わせて、縦方向の不要なスクロールを防ぐ
        if not self._bar_y:
            c_h = self.canvas.winfo_height()
            self.canvas.itemconfigure(self.window_id, height=c_h)


    # Canvas のサイズが変わったとき
    def _on_canvas_configure(self, event):
        if not self._bar_x:
            self.canvas.itemconfigure(self.window_id, width=event.width)
        # scrollregion を再評価
        self._on_interior_configure()

    # ---- ホイールを有効化/無効化（子上でも動作するように） ----
    def _activate_mousewheel(self, event=None):
        if self.OS in ('win32', 'darwin'):
            # トラックパッド2本指もここで入ってくる
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
            self.canvas.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel, add="+")
        elif self.OS == 'linux':
            self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux, add="+")
            self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux, add="+")
            self.canvas.bind_all("<Shift-Button-4>", self._on_shift_mousewheel_linux, add="+")
            self.canvas.bind_all("<Shift-Button-5>", self._on_shift_mousewheel_linux, add+"+")

    def _deactivate_mousewheel(self, event=None):
        if self.OS in ('win32', 'darwin'):
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Shift-MouseWheel>")
        elif self.OS == 'linux':
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")
            self.canvas.unbind_all("<Shift-Button-4>")
            self.canvas.unbind_all("<Shift-Button-5>")

    # ---- ホイール（Win/Mac）: “必要なときだけ” スクロール、端では止める ----
    def _on_mousewheel(self, event):
        if not self._bar_y:
            return
        y1, y2 = self.canvas.yview()
        # スクロール不要
        if y1 == 0.0 and y2 == 1.0:
            return
        # delta はデバイスにより大小様々なので、符号だけを使って 1 ステップに統一
        step = -1 if event.delta > 0 else 1
        # 端で逆方向は無視
        if (y1 <= 0.0 and step < 0) or (y2 >= 1.0 and step > 0):
            return
        self.canvas.yview_scroll(step, "units")

    def _on_shift_mousewheel(self, event):
        if not self._bar_x:
            return
        x1, x2 = self.canvas.xview()
        if x1 == 0.0 and x2 == 1.0:
            return
        step = -1 if event.delta > 0 else 1
        if (x1 <= 0.0 and step < 0) or (x2 >= 1.0 and step > 0):
            return
        self.canvas.xview_scroll(step, "units")

    # ---- ホイール（Linux） ----
    def _on_mousewheel_linux(self, event):
        if not self._bar_y:
            return
        y1, y2 = self.canvas.yview()
        if y1 == 0.0 and y2 == 1.0:
            return
        step = -1 if event.num == 4 else 1
        if (y1 <= 0.0 and step < 0) or (y2 >= 1.0 and step > 0):
            return
        self.canvas.yview_scroll(step, "units")

    def _on_shift_mousewheel_linux(self, event):
        if not self._bar_x:
            return
        x1, x2 = self.canvas.xview()
        if x1 == 0.0 and x2 == 1.0:
            return
        step = -1 if event.num == 4 else 1
        if (x1 <= 0.0 and step < 0) or (x2 >= 1.0 and step > 0):
            return
        self.canvas.xview_scroll(step, "units")

