const form = document.getElementById("chatForm");
const input = document.getElementById("questionInput");
const messages = document.getElementById("chatMessages");
const sendButton = document.getElementById("sendButton");
const languageSelect = document.getElementById("languageSelect");
const clearButton = document.getElementById("clearChat");

function addMessage(role, text, sources = [], confidence = null) {
  const wrap = document.createElement("div");
  wrap.className = `message ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "user" ? "You" : "✦";
  const body = document.createElement("div");
  body.className = "message-body";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  body.appendChild(paragraph);
  if (sources.length) {
    const sourceBox = document.createElement("div");
    sourceBox.className = "source-list";
    const label = document.createElement("strong");
    label.textContent = "Sources";
    sourceBox.appendChild(label);
    sources.forEach((source) => {
      const line = document.createElement("div");
      line.textContent = "↳ " + source;
      sourceBox.appendChild(line);
    });
    body.appendChild(sourceBox);
  }
  if (confidence !== null) {
    const meta = document.createElement("small");
    meta.className = "confidence";
    meta.textContent = confidence > 0 ? `Retrieval similarity: ${Math.round(confidence * 100)}%` : "No relevant source found";
    body.appendChild(meta);
  }
  wrap.append(avatar, body);
  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;
  return wrap;
}

async function askQuestion(question) {
  addMessage("user", question);
  const waiting = addMessage("assistant", "Searching the college knowledge base…");
  sendButton.disabled = true;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, language: languageSelect.value })
    });
    const data = await response.json();
    waiting.remove();
    if (!response.ok) throw new Error(data.error || "Request failed.");
    addMessage("assistant", data.answer, data.sources || [], data.confidence ?? 0);
  } catch (error) {
    waiting.remove();
    addMessage("assistant", `Sorry, I couldn't complete that request. ${error.message}`);
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

form?.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) return;
  input.value = "";
  input.style.height = "auto";
  askQuestion(question);
});
input?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});
input?.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});
document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.textContent.trim();
    form.requestSubmit();
  });
});
clearButton?.addEventListener("click", () => {
  messages.replaceChildren();
  addMessage("assistant", "Conversation cleared. Ask me about courses, notices, study materials or campus information.");
});
