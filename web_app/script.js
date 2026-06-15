let tg = window.Telegram.WebApp;
let user = tg.initDataUnsafe?.user || { id: 0, username: "странник" };
tg.expand();

let modal = document.getElementById("gameModal");
let modalTitle = document.getElementById("modalTitle");
let modalBody = document.getElementById("modalBody");
let oracleDiv = document.getElementById("oracle");

async function apiCall(action, data = {}) {
    data.user_id = user.id;
    data.action = action;
    try {
        let res = await fetch("/api", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });
        return await res.json();
    } catch(e) {
        console.error(e);
        return { error: "Тишина в эфире" };
    }
}

function showToast(msg, isWin = null) {
    let toast = document.createElement("div");
    toast.className = "toast-mystic";
    if (isWin === true) toast.style.borderColor = "#b8aee0";
    if (isWin === false) toast.style.borderColor = "#5a4a6a";
    toast.innerText = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2600);
}

function setOracle(text, isWin = null) {
    if (oracleDiv) {
        oracleDiv.innerHTML = `✦ ${text} ✦`;
        if (isWin === true) oracleDiv.style.borderLeftColor = "#b8aee0";
        if (isWin === false) oracleDiv.style.borderLeftColor = "#5a4a6a";
        setTimeout(() => {
            if (oracleDiv.innerHTML === `✦ ${text} ✦`) oracleDiv.innerHTML = "";
        }, 2800);
    }
}

async function refreshProfile() {
    let data = await apiCall("profile");
    if (data.coins !== undefined) {
        document.getElementById("balance").innerText = data.coins;
        document.getElementById("gamesCount").innerText = data.games;
        document.getElementById("winsCount").innerText = data.wins;
        document.getElementById("username").innerText = user.username;
    }
}

document.getElementById("bonusBtn")?.addEventListener("click", async () => {
    let data = await apiCall("bonus");
    if (data.success) {
        await refreshProfile();
        setOracle(`дар получен +${data.message}`, true);
        showToast(`+${data.message} эфира`, true);
    } else {
        showToast(data.message || "дар уже был сегодня", false);
    }
});

function openModal(title, html) {
    modalTitle.innerText = title;
    modalBody.innerHTML = html;
    modal.style.display = "flex";
}

function closeModal() {
    modal.style.display = "none";
}
document.querySelectorAll(".modal-close").forEach(btn => btn.addEventListener("click", closeModal));
window.onclick = e => { if (e.target === modal) closeModal(); };

function gameDice1() {
    let btns = "";
    for (let i = 1; i <= 6; i++) btns += `<button class="dice-btn" data-dice="${i}">${i}</button>`;
    openModal("грань судьбы", `<div class="dice-group">${btns}</div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let val = parseInt(btn.dataset.dice);
            let res = await apiCall("dice1", { guess: val });
            await refreshProfile();
            if (res.error) showToast(res.error, false);
            else if (res.win) setOracle(`выпало ${res.roll} ✦ победа +${res.message}`, true);
            else setOracle(`выпало ${res.roll} ✦ бездна ${res.message}`, false);
            closeModal();
        });
    });
}

function gameDice2() {
    let btns = "";
    for (let i = 2; i <= 12; i++) btns += `<button class="dice-btn" data-dice="${i}">${i}</button>`;
    openModal("двойной рок", `<div class="dice-group">${btns}</div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let guess = parseInt(btn.dataset.dice);
            let res = await apiCall("dice2", { guess });
            await refreshProfile();
            if (res.error) showToast(res.error, false);
            else if (res.win) setOracle(`${res.dice[0]}+${res.dice[1]}=${res.total} ✦ победа +${res.message}`, true);
            else setOracle(`${res.dice[0]}+${res.dice[1]}=${res.total} ✦ бездна ${res.message}`, false);
            closeModal();
        });
    });
}

function gameRPS() {
    openModal("дуэль", `<div style="display:flex; gap:12px; justify-content:center;">
        <button class="dice-btn" data-choice="камень">🪨 камень</button>
        <button class="dice-btn" data-choice="ножницы">✂️ ножницы</button>
        <button class="dice-btn" data-choice="бумага">📄 бумага</button>
    </div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let choice = btn.dataset.choice;
            let res = await apiCall("rps", { choice });
            await refreshProfile();
            if (res.error) showToast(res.error, false);
            else if (res.win) setOracle(`бот: ${res.bot} ✦ победа +${res.message}`, true);
            else if (res.message === "0") setOracle(`ничья (${res.bot})`, false);
            else setOracle(`бот: ${res.bot} ✦ бездна ${res.message}`, false);
            closeModal();
        });
    });
}

function gameSlots() {
    openModal("зов волн", `<button id="slotBtn" class="dice-btn" style="width:100%">🎰 крутить (1 эфир)</button>`);
    document.getElementById("slotBtn")?.addEventListener("click", async () => {
        let res = await apiCall("slots");
        await refreshProfile();
        if (res.error) showToast(res.error, false);
        else if (res.win) setOracle(`${res.reel.join(" ")} ✦ джекпот +${res.message}`, true);
        else setOracle(`${res.reel.join(" ")} ✦ тишина ${res.message}`, false);
        closeModal();
    });
}

function gameGuess() {
    let btns = "";
    for (let i = 1; i <= 10; i++) btns += `<button class="dice-btn" data-guess="${i}">${i}</button>`;
    openModal("оракул", `<div class="dice-group">${btns}</div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let guess = parseInt(btn.dataset.guess);
            let res = await apiCall("guess", { guess });
            await refreshProfile();
            if (res.error) showToast(res.error, false);
            else if (res.win) setOracle(`знак ${res.secret} ✦ победа +${res.message}`, true);
            else setOracle(`знак ${res.secret} ✦ пустота ${res.message}`, false);
            closeModal();
        });
    });
}

document.querySelectorAll(".game-rune").forEach(card => {
    card.addEventListener("click", () => {
        let game = card.dataset.game;
        if (game === "dice1") gameDice1();
        if (game === "dice2") gameDice2();
        if (game === "rps") gameRPS();
        if (game === "slots") gameSlots();
        if (game === "guess") gameGuess();
    });
});

// Питомцы
async function loadPets() {
    let data = await apiCall("get_pets");
    let myDiv = document.getElementById("myPets");
    let shopDiv = document.getElementById("shopPets");
    if (!myDiv || !shopDiv) return;
    myDiv.innerHTML = "";
    shopDiv.innerHTML = "";
    for (let p of data.pets) {
        if (p.owned) {
            myDiv.innerHTML += `<div class="pet-card">
                <div><span class="pet-name">${p.emoji} ${p.name}</span> <span class="pet-level">ур. ${p.level}</span></div>
                <div><button class="pet-btn" data-feed="${p.id}">🍖 кормить</button>
                <button class="pet-btn" data-collect="${p.id}">💾 собрать</button></div>
            </div>`;
        } else {
            shopDiv.innerHTML += `<div class="pet-card">
                <div><span class="pet-name">${p.emoji} ${p.name}</span></div>
                <div>💰 ${p.price}</div>
                <div><button class="pet-btn" data-buy="${p.id}">призвать</button></div>
            </div>`;
        }
    }
    document.querySelectorAll("[data-buy]").forEach(btn => {
        btn.addEventListener("click", async () => {
            let petId = parseInt(btn.dataset.buy);
            let res = await apiCall("buy_pet", { pet_id: petId });
            if (res.success) {
                await refreshProfile();
                await loadPets();
                showToast(res.message, true);
            } else showToast(res.message, false);
        });
    });
    document.querySelectorAll("[data-feed]").forEach(btn => {
        btn.addEventListener("click", async () => {
            let petId = parseInt(btn.dataset.feed);
            let res = await apiCall("feed_pet", { pet_id: petId });
            if (res.success) {
                await refreshProfile();
                await loadPets();
                showToast(res.message, true);
            } else showToast(res.message, false);
        });
    });
    document.querySelectorAll("[data-collect]").forEach(btn => {
        btn.addEventListener("click", async () => {
            let petId = parseInt(btn.dataset.collect);
            let res = await apiCall("collect_pet", { pet_id: petId });
            if (res.success) {
                await refreshProfile();
                showToast(`собрано +${res.earned} эфира`, true);
                if (res.earned > 0) setOracle(`+${res.earned} эфира от питомца`, true);
            }
        });
    });
}

async function loadAlliances() {
    let data = await apiCall("alliance_info");
    let panel = document.getElementById("alliancePanel");
    let topDiv = document.getElementById("topAlliances");
    if (!panel) return;
    panel.innerHTML = `<div class="alliance-card">
        <div>🏛️ твой альянс: ${data.alliance_id || "нет"}</div>
        <button id="createAllianceBtn" class="pet-btn">создать</button>
        <button id="joinAllianceBtn" class="pet-btn">вступить</button>
    </div>`;
    if (topDiv && data.top) {
        topDiv.innerHTML = data.top.map(t => `<div>🏛️ ${t[0]} — ${t[1]} эфира</div>`).join("");
    }
    document.getElementById("createAllianceBtn")?.addEventListener("click", () => {
        let name = prompt("название альянса");
        let min = parseInt(prompt("мин. эфира для входа (0-100000)") || "0");
        apiCall("create_alliance", { name, min_coins: min }).then(res => {
            if (res.success) loadAlliances();
            else showToast("ошибка", false);
        });
    });
    document.getElementById("joinAllianceBtn")?.addEventListener("click", () => {
        let id = parseInt(prompt("id альянса"));
        apiCall("join_alliance", { alliance_id: id }).then(res => {
            if (res.success) loadAlliances();
            else showToast("не удалось", false);
        });
    });
}

document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(t => t.classList.remove("active"));
        document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        let tab = btn.dataset.tab;
        document.getElementById(tab).classList.add("active");
        if (tab === "pets") loadPets();
        if (tab === "alliances") loadAlliances();
    });
});

refreshProfile();
loadPets();
loadAlliances();
