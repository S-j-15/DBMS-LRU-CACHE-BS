import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import mysql.connector
import threading

# ---------------- SQL ----------------
class SQLC:
    def __init__(self, host="localhost", user="root", passw="", db="test"):
        self.host = host
        self.user = user
        self.passw = passw
        self.db = db

    def get_connection(self):
        return mysql.connector.connect(
            host=self.host, user=self.user, password=self.passw, database=self.db
        )

    def fetch_story(self, key, version=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if version is None:
            cursor.execute(
                "SELECT text, version FROM story_versions WHERE id=%s ORDER BY version DESC LIMIT 1", (key,)
            )
        else:
            cursor.execute(
                "SELECT text, version FROM story_versions WHERE id=%s AND version=%s", (key, version)
            )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            return row[0], row[1]
        return None, None

    def write_story(self, key, text):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(version) FROM story_versions WHERE id=%s", (key,))
        row = cursor.fetchone()
        latest_version = row[0] if row[0] else 0
        new_version = latest_version + 1
        cursor.execute(
            "INSERT INTO story_versions (id, version, text) VALUES (%s, %s, %s)", (key, new_version, text)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return new_version

# ---------------- Cache ----------------
class Node:
    def __init__(self, key, version, text, dirty=False):
        self.key = key
        self.version = version
        self.text = text
        self.dirty = dirty
        self.prev = None
        self.next = None

class LinkedList:
    def __init__(self):
        self.front = None
        self.rear = None

    def put_rear(self, node):
        if self.front is None:
            self.front = self.rear = node
        else:
            self.rear.next = node
            node.prev = self.rear
            self.rear = node

    def remove_front(self):
        if not self.front:
            return None
        node = self.front
        self.front = node.next
        if self.front:
            self.front.prev = None
        else:
            self.rear = None
        return node

    def remove_node(self, node):
        if node.prev:
            node.prev.next = node.next
        else:
            self.front = node.next
        if node.next:
            node.next.prev = node.prev
        else:
            self.rear = node.prev
        node.prev = node.next = None

class LRUCache:
    def __init__(self, capacity, sql):
        self.capacity = capacity
        self.sql = sql
        self.map = {}  # (key, version) -> Node
        self.list = LinkedList()

    def get(self, key, version=None):
        # Try latest if version=None
        node = None
        if version is None:
            # pick latest version from cache
            latest_node = None
            for (k, v), n in self.map.items():
                if k == key and (latest_node is None or v > latest_node.version):
                    latest_node = n
            node = latest_node
        else:
            node = self.map.get((key, version))

        if node:
            self.list.remove_node(node)
            self.list.put_rear(node)
            return node.text, node.version

        # Not in cache -> fetch from DB
        text, ver = self.sql.fetch_story(key, version)
        if text is None:
            return None, None
        new_node = Node(key, ver, text, dirty=False)
        self._add_node(new_node)
        return text, ver

    def put(self, key, text):
        new_version = self.sql.write_story(key, text)
        node = Node(key, new_version, text, dirty=False)
        self._add_node(node)
        return new_version

    def _add_node(self, node):
        if len(self.map) >= self.capacity:
            old = self.list.remove_front()
            if old:
                self.map.pop((old.key, old.version))
                if old.dirty:
                    self.sql.write_story(old.key, old.text)
        self.list.put_rear(node)
        self.map[(node.key, node.version)] = node

# ---------------- App ----------------
class LRUApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LRU Story Cache Versioned")
        self.geometry("900x520")
        self.sql = None
        self.lru = None
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="both", expand=True)

        conn_frame = ttk.LabelFrame(frm, text="DB Connection")
        conn_frame.pack(fill="x", padx=4, pady=4)

        ttk.Label(conn_frame, text="Host:").grid(row=0, column=0, sticky="w")
        self.host_e = ttk.Entry(conn_frame); self.host_e.insert(0,"localhost"); self.host_e.grid(row=0,column=1)
        ttk.Label(conn_frame, text="User:").grid(row=0, column=2, sticky="w")
        self.user_e = ttk.Entry(conn_frame); self.user_e.insert(0,"root"); self.user_e.grid(row=0,column=3)
        ttk.Label(conn_frame, text="Password:").grid(row=1,column=0, sticky="w")
        self.pass_e = ttk.Entry(conn_frame, show="*"); self.pass_e.grid(row=1,column=1)
        ttk.Label(conn_frame, text="Database:").grid(row=1,column=2, sticky="w")
        self.db_e = ttk.Entry(conn_frame); self.db_e.insert(0,"test"); self.db_e.grid(row=1,column=3)
        ttk.Label(conn_frame, text="Cache capacity:").grid(row=2,column=0, sticky="w")
        self.cap_e = ttk.Entry(conn_frame,width=6); self.cap_e.insert(0,"10"); self.cap_e.grid(row=2,column=1)
        self.connect_btn = ttk.Button(conn_frame,text="Connect", command=self._connect_db); self.connect_btn.grid(row=2,column=3)

        fs_frame = ttk.LabelFrame(frm, text="Fetch/Edit Story")
        fs_frame.pack(fill="both", expand=True, padx=4,pady=4)
        ttk.Label(fs_frame,text="Key:").grid(row=0,column=0)
        self.key_e = ttk.Entry(fs_frame,width=10); self.key_e.grid(row=0,column=1)
        ttk.Label(fs_frame,text="Version (optional):").grid(row=0,column=2)
        self.version_e = ttk.Entry(fs_frame,width=5); self.version_e.grid(row=0,column=3)
        self.fetch_btn = ttk.Button(fs_frame,text="Fetch",command=self._fetch_story,state="disabled"); self.fetch_btn.grid(row=0,column=4,padx=6)
        self.save_btn = ttk.Button(fs_frame,text="Save (new version)",command=self._save_story,state="disabled"); self.save_btn.grid(row=0,column=5,padx=6)
        self.status_lbl = ttk.Label(fs_frame,text="Not connected",foreground="blue"); self.status_lbl.grid(row=0,column=6)

        self.story_txt = scrolledtext.ScrolledText(fs_frame,height=12,wrap="word"); self.story_txt.grid(row=1,column=0,columnspan=7,sticky="nsew", pady=6)
        fs_frame.rowconfigure(1, weight=1); fs_frame.columnconfigure(6, weight=1)

        cache_frame = ttk.LabelFrame(frm,text="Cache (LRU order front=LRU)")
        cache_frame.pack(fill="both", padx=4,pady=4, expand=False)
        self.cache_listbox = tk.Listbox(cache_frame,height=8); self.cache_listbox.pack(side="left",fill="both",expand=True,padx=4,pady=4)
        self.refresh_cache_btn = ttk.Button(cache_frame,text="Refresh Cache View",command=self._refresh_cache,state="disabled"); self.refresh_cache_btn.pack(side="right",padx=4,pady=4)

    def _connect_db(self):
        host=self.host_e.get().strip(); user=self.user_e.get().strip(); pwd=self.pass_e.get(); db=self.db_e.get().strip()
        try: cap=int(self.cap_e.get().strip()); assert cap>0
        except: messagebox.showerror("Capacity error","Enter positive integer"); return
        try:
            sql = SQLC(host,user,pwd,db); conn=sql.get_connection(); conn.close()
        except Exception as e:
            messagebox.showerror("DB error",str(e)); return
        self.sql = SQLC(host,user,pwd,db)
        self.lru = LRUCache(cap,self.sql)
        self.fetch_btn.config(state="normal"); self.save_btn.config(state="normal"); self.refresh_cache_btn.config(state="normal")
        self.status_lbl.config(text=f"Connected {db}@{host}")

    def _fetch_story(self):
        if self.lru is None: messagebox.showwarning("Not connected","Connect DB first"); return
        try:
            key=int(self.key_e.get().strip())
            version=int(self.version_e.get().strip()) if self.version_e.get().strip() else None
        except: messagebox.showerror("Input error","Key/Version must be int"); return
        def db_fetch():
            val, ver = self.lru.get(key, version)
            if val is None:
                self.after(0, lambda: self._set_story_text(f"(No story key={key}, version={version})"))
                self.after(0, lambda: self.status_lbl.config(text="Not found"))
            else:
                self.after(0, lambda: self._set_story_text(val))
                self.after(0, lambda: self.status_lbl.config(text=f"Fetched key={key}, version={ver}"))
                self.after(0, self._refresh_cache)
        threading.Thread(target=db_fetch,daemon=True).start()

    def _save_story(self):
        if self.lru is None: messagebox.showwarning("Not connected","Connect DB first"); return
        try: key=int(self.key_e.get().strip())
        except: messagebox.showerror("Key error","Key must be int"); return
        txt=self.story_txt.get("1.0",tk.END).rstrip("\n")
        new_ver=self.lru.put(key,txt)
        self.status_lbl.config(text=f"Saved key={key} as version={new_ver}")
        self._refresh_cache()

    def _set_story_text(self,text):
        self.story_txt.delete("1.0",tk.END); self.story_txt.insert(tk.END,text)

    def _refresh_cache(self):
        self.cache_listbox.delete(0,tk.END)
        if not self.lru: return
        cur=self.lru.list.front
        while cur:
            self.cache_listbox.insert(tk.END,f"{cur.key} v{cur.version}")
            cur=cur.next

    def _on_close(self):
        self.destroy()

if __name__=="__main__":
    app = LRUApp()
    app.mainloop()
