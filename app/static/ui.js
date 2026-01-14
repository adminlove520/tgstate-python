// 主题系统
const Theme = {
    key: 'tgstate_theme_pref',
    
    init() {
        const pref = localStorage.getItem(this.key) || 'auto';
        this.set(pref, false);
        this.setupListeners();
    },
    
    set(mode, save = true) {
        if (save) localStorage.setItem(this.key, mode);
        
        let effectiveMode = mode;
        if (mode === 'auto') {
            effectiveMode = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        
        document.documentElement.setAttribute('data-theme', effectiveMode);
        
        // 更新 UI 状态
        const toggles = document.querySelectorAll('.theme-toggle-btn');
        toggles.forEach(btn => {
            const label = btn.querySelector('.theme-label');
            if (label) {
                const map = { 'auto': '跟随系统', 'light': '浅色模式', 'dark': '深色模式' };
                label.textContent = map[mode];
            }
        });
        
        // 触发事件
        window.dispatchEvent(new CustomEvent('themeChanged', { detail: mode }));
    },
    
    setupListeners() {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            if (localStorage.getItem(this.key) === 'auto') {
                this.set('auto', false);
            }
        });
    },

    cycle() {
        const current = localStorage.getItem(this.key) || 'auto';
        const map = { 'auto': 'light', 'light': 'dark', 'dark': 'auto' };
        this.set(map[current]);
    }
};

// Toast 提示系统
const Toast = {
    container: null,
    
    init() {
        if (!document.querySelector('.toast-container')) {
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            document.body.appendChild(this.container);
        } else {
            this.container = document.querySelector('.toast-container');
        }
    },
    
    show(message, type = 'success') {
        this.init();
        
        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        
        const icon = type === 'success' 
            ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'
            : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
            
        el.innerHTML = `
            <div class="toast-icon">${icon}</div>
            <div class="toast-content">${message}</div>
        `;
        
        this.container.appendChild(el);
        
        // 动画进入
        requestAnimationFrame(() => {
            el.style.transform = 'translateY(0)';
            el.style.opacity = '1';
        });
        
        setTimeout(() => {
            el.style.opacity = '0';
            el.style.transform = 'translateY(20px)';
            setTimeout(() => el.remove(), 300);
        }, 3000);
    }
};

// 通用工具
const Utils = {
    async copy(text) {
        try {
            await navigator.clipboard.writeText(text);
            Toast.show('已复制到剪贴板');
            return true;
        } catch (err) {
            Toast.show('复制失败，请手动复制', 'error');
            return false;
        }
    },
    
    setLoading(btn, isLoading) {
        if (!btn) return;
        if (isLoading) {
            btn.dataset.originalText = btn.innerHTML;
            btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg> 处理中...`;
            btn.classList.add('loading');
            btn.disabled = true;
        } else {
            btn.innerHTML = btn.dataset.originalText || btn.innerHTML;
            btn.classList.remove('loading');
            btn.disabled = false;
        }
    }
};

// 认证系统
const Auth = {
    async logout() {
        if (!confirm('确定要退出登录吗？')) return;
        
        try {
            const res = await fetch('/api/auth/logout', {
                method: 'POST',
                // 确保携带凭证（Cookies）
                credentials: 'include' 
            });
            
            if (res.ok) {
                // 清理可能存在的本地状态
                // localStorage.removeItem('some_key'); 
                
                // 强制跳转到登录页，并替换历史记录，防止后退
                window.location.replace('/login');
            } else {
                Toast.show('退出失败，请刷新重试', 'error');
            }
        } catch (e) {
            console.error(e);
            Toast.show('网络错误', 'error');
        }
    }
};

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    Theme.init();
    
    // 侧边栏/移动端菜单切换

    const toggleBtn = document.querySelector('.menu-toggle');
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.querySelector('.sidebar-overlay');
    
    if (toggleBtn && sidebar) {
        toggleBtn.addEventListener('click', () => {
            sidebar.classList.toggle('active');
            if (overlay) overlay.classList.toggle('active');
        });
    }
    
    if (overlay) {
        overlay.addEventListener('click', () => {
            sidebar.classList.remove('active');
            overlay.classList.remove('active');
        });
    }
});
