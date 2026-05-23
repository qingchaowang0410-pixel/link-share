function appState() {
  return {
    view: "dashboard",
    categories: [],
    allSharers: [],
    stats: { total: 0, unread: 0, week_new: 0, by_category: [], recent: [], top_sharers: [] },
    links: [],
    filters: { q: "", category: "", is_read: "", sharer: "", tag: "" },
    form: {
      url: "",
      title: "",
      description: "",
      category: "其他",
      sharer: "",
      tagsRaw: "",
      note: "",
      is_read: false,
    },
    addMessage: "",
    addMessageOk: false,
    editing: null,
    recentAdds: [],
    fetching: false,
    fetchHint: "",
    fetchOk: false,
    _lastFetchedUrl: "",
    userName: "",
    authToken: "",
    isAdmin: false,
    // 登录/注册弹窗
    askLogin: false,
    authMode: "login", // "login" | "register"
    registerOpen: false,
    loginForm: { username: "", password: "", invite: "" },
    loginError: "",
    // 个人资料 / 改密弹窗
    showProfile: false,
    pwdForm: { old: "", new1: "", new2: "" },
    pwdMessage: "",
    pwdMessageOk: false,

    emptyForm() {
      return {
        url: "",
        title: "",
        description: "",
        category: "其他",
        sharer: "",
        tagsRaw: "",
        note: "",
        is_read: false,
      };
    },

    async init() {
      this.authToken = localStorage.getItem("linkhub_auth_token") || "";

      // 检查后端登录/注册状态
      const status = await fetch("/api/auth-status").then((r) => r.json()).catch(() => ({ required: true, register_open: false }));
      this.registerOpen = !!status.register_open;

      if (!this.authToken) {
        this.openLogin();
        return; // 等用户登录后才继续 init
      }

      await this.bootAfterAuth();
    },

    openLogin() {
      this.askLogin = true;
      this.authMode = this.registerOpen ? this.authMode : "login";
      this.$nextTick(() => this.$refs.loginUser && this.$refs.loginUser.focus());
    },

    async bootAfterAuth() {
      try {
        // 拿当前登录用户信息（用户名 = 操作记录里的"由谁添加"）
        const me = await this.api("/api/me");
        this.userName = me.username || "";
        this.isAdmin = !!me.is_admin;
        const cats = await this.api("/api/categories");
        this.categories = cats.categories;
        await this.refreshAll();
      } catch (e) {
        if (String(e.message).includes("需要登录")) {
          this.logout(true);
        }
      }
    },

    async submitLogin() {
      const u = (this.loginForm.username || "").trim();
      const p = this.loginForm.password || "";
      if (!u || !p) return;
      this.loginError = "";
      try {
        const body =
          this.authMode === "register"
            ? { username: u, password: p, invite_code: (this.loginForm.invite || "").trim() }
            : { username: u, password: p };
        const path = this.authMode === "register" ? "/api/register" : "/api/login";
        const res = await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || "登录失败");
        }
        const data = await res.json();
        this.authToken = data.token || "";
        localStorage.setItem("linkhub_auth_token", this.authToken);
        this.askLogin = false;
        this.loginForm = { username: "", password: "", invite: "" };
        await this.bootAfterAuth();
      } catch (e) {
        this.loginError = e.message || "操作失败";
      }
    },

    toggleAuthMode() {
      this.authMode = this.authMode === "login" ? "register" : "login";
      this.loginError = "";
    },

    logout(silent) {
      this.authToken = "";
      this.userName = "";
      this.isAdmin = false;
      localStorage.removeItem("linkhub_auth_token");
      this.openLogin();
    },

    // 我能否编辑/删除这条链接：管理员能动所有，普通用户只能动自己加的
    canEdit(link) {
      if (this.isAdmin) return true;
      return !!link.added_by && link.added_by === this.userName;
    },

    openProfile() {
      this.showProfile = true;
      this.pwdForm = { old: "", new1: "", new2: "" };
      this.pwdMessage = "";
    },

    async submitChangePassword() {
      this.pwdMessage = "";
      if (this.pwdForm.new1.length < 6) {
        this.pwdMessage = "新密码至少 6 位";
        this.pwdMessageOk = false;
        return;
      }
      if (this.pwdForm.new1 !== this.pwdForm.new2) {
        this.pwdMessage = "两次输入的新密码不一致";
        this.pwdMessageOk = false;
        return;
      }
      try {
        await this.api("/api/change-password", {
          method: "POST",
          body: JSON.stringify({
            old_password: this.pwdForm.old,
            new_password: this.pwdForm.new1,
          }),
        });
        this.pwdMessage = "✓ 密码已修改";
        this.pwdMessageOk = true;
        this.pwdForm = { old: "", new1: "", new2: "" };
        setTimeout(() => (this.showProfile = false), 1200);
      } catch (e) {
        this.pwdMessage = e.message || "修改失败";
        this.pwdMessageOk = false;
      }
    },

    async refreshAll() {
      await Promise.all([
        this.loadStats(),
        this.loadLinks(),
        this.loadSharers(),
        this.loadRecentAdds(),
      ]);
    },

    async loadRecentAdds() {
      const data = await this.api("/api/links");
      this.recentAdds = data.links.slice(0, 10);
    },

    formatTime(s) {
      if (!s) return "";
      // 后端返回形如 "2026-05-23 16:17:16"
      const now = new Date();
      const t = new Date(s.replace(" ", "T"));
      const diffMs = now - t;
      const min = Math.floor(diffMs / 60000);
      if (min < 1) return "刚刚";
      if (min < 60) return min + " 分钟前";
      const h = Math.floor(min / 60);
      if (h < 24) return h + " 小时前";
      const d = Math.floor(h / 24);
      if (d < 7) return d + " 天前";
      return s.slice(5, 10); // MM-DD
    },

    switchView(v) {
      this.view = v;
      if (v === "library") {
        this.filters.sharer = "";
        this.filters.tag = "";
        this.loadLinks();
      }
      if (v === "sharers") {
        this.filters.sharer = "";
        this.loadSharers();
      }
      if (v === "dashboard") this.loadStats();
    },

    async api(path, options = {}) {
      const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      };
      if (this.userName) {
        headers["X-User-Name"] = encodeURIComponent(this.userName);
      }
      if (this.authToken) {
        headers["X-Auth-Token"] = this.authToken;
      }
      const res = await fetch(path, { ...options, headers });
      if (res.status === 401) {
        // token 失效 → 清掉，弹登录框
        this.authToken = "";
        localStorage.removeItem("linkhub_auth_token");
        this.openLogin();
        throw new Error("需要登录");
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "请求失败" }));
        throw new Error(err.detail || "请求失败");
      }
      return res.json();
    },

    async loadStats() {
      this.stats = await this.api("/api/stats");
    },

    async loadLinks() {
      const params = new URLSearchParams();
      if (this.filters.q) params.set("q", this.filters.q);
      if (this.filters.category) params.set("category", this.filters.category);
      if (this.filters.is_read !== "") params.set("is_read", this.filters.is_read);
      if (this.filters.sharer) params.set("sharer", this.filters.sharer);
      if (this.filters.tag) params.set("tag", this.filters.tag);
      const data = await this.api("/api/links?" + params.toString());
      this.links = data.links;
    },

    async loadSharers() {
      const data = await this.api("/api/sharers");
      this.allSharers = data.sharers;
    },

    async fetchMeta() {
      const url = this.form.url.trim();
      if (!url) {
        this.fetchHint = "";
        return;
      }
      // 简单去重：同一个 URL 不重复抓
      if (url === this._lastFetchedUrl) return;
      this._lastFetchedUrl = url;

      this.fetching = true;
      this.fetchHint = "";
      try {
        const res = await this.api("/api/fetch-meta?url=" + encodeURIComponent(url));
        // 分类总是按域名猜（即使抓取失败）
        if (res.category) this.form.category = res.category;
        // 只在用户没手动填过的字段写入抓取结果
        if (res.title && !this.form.title.trim()) this.form.title = res.title;
        if (res.description && !this.form.description.trim()) this.form.description = res.description;

        if (res.ok) {
          this.fetchOk = true;
          this.fetchHint = "✓ 已自动填充标题和简介，可继续修改";
        } else {
          this.fetchOk = false;
          this.fetchHint = "⚠ 抓取失败，请手动填写标题" + (res.error ? "（" + res.error + "）" : "");
        }
      } catch (e) {
        this.fetchOk = false;
        this.fetchHint = "⚠ 抓取失败：" + e.message + "，请手动填写";
      } finally {
        this.fetching = false;
      }
    },

    async submitLink() {
      const url = this.form.url.trim();
      if (!url) return;
      try {
        const tags = this.form.tagsRaw
          .split(/[,，]/)
          .map((t) => t.trim())
          .filter(Boolean);
        await this.api("/api/links", {
          method: "POST",
          body: JSON.stringify({
            url,
            title: this.form.title,
            description: this.form.description,
            category: this.form.category,
            sharer: this.form.sharer,
            tags,
            note: this.form.note,
            is_read: this.form.is_read,
          }),
        });
        this.addMessage = "✓ 已保存";
        this.addMessageOk = true;
        this.resetForm();
        await this.refreshAll();
        setTimeout(() => (this.addMessage = ""), 2000);
      } catch (e) {
        this.addMessage = "保存失败：" + e.message;
        this.addMessageOk = false;
      }
    },

    resetForm() {
      this.form = this.emptyForm();
      this.fetchHint = "";
      this._lastFetchedUrl = "";
    },

    recordClick(link) {
      if (!link || !link.id) return;
      // 异步上报，不等结果、不阻塞跳转
      this.api(`/api/links/${link.id}/click`, { method: "POST" }).catch(() => {});
      // 本地乐观更新计数，避免回到看板还是旧数据
      if (typeof link.click_count === "number") link.click_count += 1;
    },

    async toggleRead(link) {
      link.is_read = !link.is_read;
      await this.api(`/api/links/${link.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_read: link.is_read }),
      });
      this.loadStats();
    },

    async deleteLink(link) {
      if (!confirm(`确定删除「${link.title || link.url}」？`)) return;
      await this.api(`/api/links/${link.id}`, { method: "DELETE" });
      await this.refreshAll();
    },

    editLink(link) {
      this.editing = {
        ...link,
        _tagsRaw: link.tags.join(", "),
      };
    },

    async saveEdit() {
      const e = this.editing;
      const tags = e._tagsRaw
        .split(/[,，]/)
        .map((t) => t.trim())
        .filter(Boolean);
      await this.api(`/api/links/${e.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          url: e.url,
          title: e.title,
          description: e.description,
          category: e.category,
          sharer: e.sharer_name || "",
          tags,
          note: e.note,
          is_read: e.is_read,
        }),
      });
      this.editing = null;
      await this.refreshAll();
    },

    openSharer(name) {
      if (!name) return;
      this.view = "sharers";
      this.filters.sharer = name;
      this.loadLinks();
    },

    clearSharerFilter() {
      this.filters.sharer = "";
      this.loadSharers();
    },

    filterByTag(tag) {
      this.view = "library";
      this.filters.tag = tag;
      this.filters.sharer = "";
      this.loadLinks();
    },

    clearFilters() {
      this.filters = { q: "", category: "", is_read: "", sharer: "", tag: "" };
      this.loadLinks();
    },
  };
}
