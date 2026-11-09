"use strict";

(() => {
  const state = {
    configured: false,
    running: false,
  };

  const elements = {
    form: document.querySelector("#agentForm"),
    compareSymbol: document.querySelector("#agentCompareSymbol"),
    question: document.querySelector("#agentQuestion"),
    submit: document.querySelector("#agentSubmit"),
    status: document.querySelector("#agentStatus"),
    empty: document.querySelector("#agentEmpty"),
    response: document.querySelector("#agentResponse"),
    responseMeta: document.querySelector("#agentResponseMeta"),
    answer: document.querySelector("#agentAnswer"),
  };

  document.addEventListener("DOMContentLoaded", () => {
    elements.form.addEventListener("submit", analyze);
    elements.question.addEventListener("input", updateSubmitState);
    checkHealth();
  });

  async function checkHealth() {
    setStatus("检查中", "pending");
    try {
      const response = await fetch("/api/agent/health", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      state.configured = Boolean(payload.configured && payload.data_available);

      if (!payload.data_available) {
        setStatus("等待回测数据", "offline");
      } else if (!payload.configured) {
        setStatus("未配置模型", "offline");
      } else {
        setStatus(payload.model, "ready");
      }
    } catch (_error) {
      state.configured = false;
      setStatus("服务不可用", "offline");
    }
    updateSubmitState();
  }

  async function analyze(event) {
    event.preventDefault();
    const question = buildQuestion();
    if (!state.configured || state.running || question.length < 2) return;

    state.running = true;
    elements.empty.textContent = "正在分析最新回测结果";
    elements.empty.hidden = false;
    elements.response.hidden = true;
    elements.submit.textContent = "分析中...";
    updateSubmitState();

    try {
      const response = await fetch("/api/agent/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }

      // 二次渲染：将模型 Markdown 转为安全 DOM，不执行模型返回的 HTML。
      // 图表渲染：优先使用本地 marked/DOMPurify/Mermaid，失败时回退到内置安全渲染器。
      await renderAnswer(payload.answer);
      elements.responseMeta.textContent = `${payload.model} | 数据时间 ${formatTimestamp(payload.as_of)}`;
      elements.empty.hidden = true;
      elements.response.hidden = false;
    } catch (error) {
      elements.empty.textContent = error instanceof Error ? error.message : String(error);
      elements.empty.hidden = false;
      elements.response.hidden = true;
    } finally {
      state.running = false;
      elements.submit.textContent = "开始分析";
      updateSubmitState();
    }
  }

  function buildQuestion() {
    const main = elements.question.value.trim();
    const compare = elements.compareSymbol.value.trim();
    const selected = document.querySelector("#symbolInput")?.value.trim();
    const base = main || "请分析当前记录的真实行情表现与风险。";
    const parts = [base];
    if (selected) parts.push(`当前股票代码：${selected}`);
    if (compare) parts.push(`对比股票代码：${compare}`);
    parts.push("请基于已保存的历史记录与最新抓取结果进行对比，说明差异、风险和可能原因。");
    return parts.join("\n\n");
  }

  function setStatus(label, mode) {
    elements.status.textContent = label;
    elements.status.dataset.status = mode;
  }

  function updateSubmitState() {
    elements.submit.disabled = !state.configured
      || state.running
      || elements.question.value.trim().length < 2;
  }

  async function renderAnswer(source) {
    if (!window.marked || !window.DOMPurify) {
      elements.answer.replaceChildren(renderMarkdown(source));
      return;
    }

    const html = window.marked.parse(String(source || ""), {
      breaks: true,
      gfm: true,
    });
    const safeHtml = window.DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
    });
    elements.answer.innerHTML = safeHtml;

    const diagrams = [...elements.answer.querySelectorAll("pre > code.language-mermaid")];
    if (window.mermaid && diagrams.length) {
      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "base",
        themeVariables: {
          primaryColor: "#e4f2ed",
          primaryTextColor: "#17302b",
          primaryBorderColor: "#6da998",
          lineColor: "#4b756b",
          secondaryColor: "#fff1e9",
          tertiaryColor: "#f7faf8",
        },
      });
    }
    for (const code of diagrams) {
      const sourceText = code.textContent || "";
      const container = code.closest("pre");
      if (!container || !window.mermaid || !sourceText.trim()) continue;
      const wrapper = document.createElement("div");
      wrapper.className = "agent-diagram";
      try {
        const diagramId = `agent-diagram-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const rendered = await window.mermaid.render(diagramId, sourceText);
        wrapper.innerHTML = window.DOMPurify.sanitize(rendered.svg, {
          USE_PROFILES: { svg: true, svgFilters: true },
        });
        container.replaceWith(wrapper);
      } catch (_error) {
        wrapper.className = "agent-diagram agent-diagram-error";
        wrapper.textContent = "图表暂时无法渲染，以下为原始图表代码：\n" + sourceText;
        container.replaceWith(wrapper);
      }
    }
  }

  // 二次渲染：仅支持标题、列表、引用、代码和加粗等展示所需语法。
  function renderMarkdown(source) {
    const fragment = document.createDocumentFragment();
    const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    let paragraphLines = [];
    let list = null;
    let quoteLines = [];
    let codeLines = [];
    let codeLanguage = "";
    let inCode = false;

    const flushParagraph = () => {
      if (!paragraphLines.length) return;
      const paragraph = document.createElement("p");
      appendInlineMarkdown(paragraph, paragraphLines.join(" "));
      fragment.appendChild(paragraph);
      paragraphLines = [];
    };
    const flushList = () => {
      if (!list) return;
      fragment.appendChild(list);
      list = null;
    };
    const flushQuote = () => {
      if (!quoteLines.length) return;
      const quote = document.createElement("blockquote");
      appendInlineMarkdown(quote, quoteLines.join(" "));
      fragment.appendChild(quote);
      quoteLines = [];
    };
    const flushCode = () => {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      if (codeLanguage) code.dataset.language = codeLanguage;
      code.textContent = codeLines.join("\n");
      pre.appendChild(code);
      fragment.appendChild(pre);
      codeLines = [];
      codeLanguage = "";
    };

    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      const fence = line.match(/^```([\w-]*)\s*$/);
      if (fence) {
        flushParagraph();
        flushList();
        flushQuote();
        if (inCode) flushCode();
        else codeLanguage = fence[1];
        inCode = !inCode;
        continue;
      }
      if (inCode) {
        codeLines.push(rawLine);
        continue;
      }
      if (!line.trim()) {
        flushParagraph();
        flushList();
        flushQuote();
        continue;
      }

      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        flushList();
        flushQuote();
        const level = Math.min(heading[1].length + 2, 6);
        const title = document.createElement(`h${level}`);
        appendInlineMarkdown(title, heading[2]);
        fragment.appendChild(title);
        continue;
      }

      const listItem = line.match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.+)$/);
      if (listItem) {
        flushParagraph();
        flushQuote();
        const listTag = listItem[2] ? "ol" : "ul";
        if (!list || list.tagName.toLowerCase() !== listTag) {
          flushList();
          list = document.createElement(listTag);
        }
        const item = document.createElement("li");
        appendInlineMarkdown(item, listItem[3]);
        list.appendChild(item);
        continue;
      }

      const quote = line.match(/^>\s?(.*)$/);
      if (quote) {
        flushParagraph();
        flushList();
        quoteLines.push(quote[1]);
        continue;
      }

      flushList();
      flushQuote();
      paragraphLines.push(line.trim());
    }

    if (inCode) flushCode();
    flushParagraph();
    flushList();
    flushQuote();
    return fragment;
  }

  function appendInlineMarkdown(parent, source) {
    const tokens = String(source).split(/(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__)/g);
    for (const token of tokens) {
      if (!token) continue;
      if (token.startsWith("`") && token.endsWith("`")) {
        const code = document.createElement("code");
        code.textContent = token.slice(1, -1);
        parent.appendChild(code);
      } else if (
        (token.startsWith("**") && token.endsWith("**"))
        || (token.startsWith("__") && token.endsWith("__"))
      ) {
        const strong = document.createElement("strong");
        strong.textContent = token.slice(2, -2);
        parent.appendChild(strong);
      } else {
        parent.appendChild(document.createTextNode(token));
      }
    }
  }

  function formatTimestamp(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }
})();
