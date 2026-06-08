// web_app/script.js
let tg = window.Telegram.WebApp;
let user = tg.initDataUnsafe?.user || { id: 0, username: "СТРАННИК" };
tg.expand();

// Глобальные переменные
let modal = document.getElementById("gameModal");
let modalTitle = document.getElementById("modalTitle");
let modalBody = document.getElementById("modalBody");
let resultDiv = document.getElementById("oracle-response");

// ========== API ВЫЗОВЫ ==========
async function apiCall(action, data = {}) {
    data.user_id = user.id;
    data.action = action;
    try {
        let resp = await fetch("/api", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });
        return await resp.json();
    } catch(e) {
        console.error(e);
        return { error: "Ошибка связи" };
    }
}

// ========== УВЕДОМЛЕНИЯ ==========
function showToast(msg, isError = false) {
    let toast = document.createElement("div");
    toast.className = "toast-mystic";
    toast.innerText = msg;
    toast.style.borderColor = isError ? "#ff8888" : "#7c93ff";
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2500);
}

function setGameResult(text, isWin = null) {
    if (resultDiv) {
        resultDiv.innerHTML = `✦ ${text} ✦`;
        setTimeout(() => {
            if (resultDiv.innerHTML === `✦ ${text} ✦`) resultDiv.innerHTML = "";
        }, 2800);
    }
}

// ========== ОБНОВЛЕНИЕ ПРОФИЛЯ ==========
async function refreshProfile() {
    let data = await apiCall("profile");
    if (data.coins !== undefined) {
        document.getElementById("balance").innerText = data.coins;
        document.getElementById("gamesCount").innerText = data.games;
        document.getElementById("winsCount").innerText = data.wins;
        document.getElementById("username").innerText = user.username || "СТРАННИК";
    }
}

// ========== БОНУС ==========
document.getElementById("bonusBtn")?.addEventListener("click", async () => {
    let data = await apiCall("bonus");
    if (data.success) {
        await refreshProfile();
        setGameResult(`ДАР ПОЛУЧЕН +${data.message} ЭФИРА`);
        showToast(`+${data.message} эфира`);
    } else {
        showToast("Дар уже был сегодня", true);
    }
});

// ========== МОДАЛЬНОЕ ОКНО ==========
function openModal(title, contentHtml) {
    modalTitle.innerText = title;
    modalBody.innerHTML = contentHtml;
    modal.style.display = "flex";
}

function closeModal() {
    modal.style.display = "none";
}
document.querySelectorAll(".modal-close").forEach(btn => {
    btn.addEventListener("click", closeModal);
});
window.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

// ========== ИГРЫ ==========
// 1. Грань Судьбы (1 кубик)
function gameDice1() {
    let btns = "";
    for (let i = 1; i <= 6; i++) btns += `<button class="dice-btn" data-dice="${i}">${i}</button>`;
    openModal("ГРАНЬ СУДЬБЫ", `<div class="dice-group">${btns}</div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let val = parseInt(btn.dataset.dice);
            let res = await apiCall("dice1", { guess: val });
            await refreshProfile();
            if (res.error) showToast(res.error, true);
            else if (res.win) setGameResult(`ВЫПАЛО ${res.roll} ✦ ПОБЕДА +${res.message} ЭФИРА`);
            else setGameResult(`ВЫПАЛО ${res.roll} ✦ ПОРАЖЕНИЕ ${res.message} ЭФИРА`);
            closeModal();
        });
    });
}

// 2. Двойной Рок (2 кубика)
function gameDice2() {
    let btns = "";
    for (let i = 2; i <= 12; i++) btns += `<button class="dice-btn" data-dice="${i}">${i}</button>`;
    openModal("ДВОЙНОЙ РОК", `<div class="dice-group">${btns}</div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let guess = parseInt(btn.dataset.dice);
            let res = await apiCall("dice2", { guess });
            await refreshProfile();
            if (res.error) showToast(res.error, true);
            else if (res.win) setGameResult(`${res.dice[0]}+${res.dice[1]}=${res.total} ✦ ПОБЕДА +${res.message} ЭФИРА`);
            else setGameResult(`${res.dice[0]}+${res.dice[1]}=${res.total} ✦ ПОРАЖЕНИЕ ${res.message} ЭФИРА`);
            closeModal();
        });
    });
}

// 3. Дуэль (КНБ)
function gameRPS() {
    openModal("ДУЭЛЬ", `<div class="rps-group">
        <button class="rps-btn" data-choice="камень">🪨 КАМЕНЬ</button>
        <button class="rps-btn" data-choice="ножницы">✂️ НОЖНИЦЫ</button>
        <button class="rps-btn" data-choice="бумага">📄 БУМАГА</button>
    </div>`);
    document.querySelectorAll("#modalBody .rps-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let choice = btn.dataset.choice;
            let res = await apiCall("rps", { choice });
            await refreshProfile();
            if (res.error) showToast(res.error, true);
            else if (res.win) setGameResult(`БОТ: ${res.bot} ✦ ПОБЕДА +${res.message} ЭФИРА`);
            else if (res.message === "0") setGameResult(`НИЧЬЯ (${res.bot})`);
            else setGameResult(`БОТ: ${res.bot} ✦ ПОРАЖЕНИЕ ${res.message} ЭФИРА`);
            closeModal();
        });
    });
}

// 4. Слоты
function gameSlots() {
    openModal("ЗОВ ВОЛН", `<button class="slot-spin" id="slotSpinBtn">🎰 ЗАПУСТИТЬ (1 эфир)</button>`);
    document.getElementById("slotSpinBtn")?.addEventListener("click", async () => {
        let res = await apiCall("slots");
        await refreshProfile();
        if (res.error) showToast(res.error, true);
        else if (res.win) setGameResult(`${res.reel.join(" ")} ✦ ДЖЕКПОТ +${res.message} ЭФИРА`);
        else setGameResult(`${res.reel.join(" ")} ✦ ТИШИНА ${res.message} ЭФИРА`);
        closeModal();
    });
}

// 5. Оракул (угадай число)
function gameGuess() {
    let btns = "";
    for (let i = 1; i <= 10; i++) btns += `<button class="dice-btn" data-guess="${i}">${i}</button>`;
    openModal("ОРАКУЛ", `<div class="dice-group">${btns}</div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let guess = parseInt(btn.dataset.guess);
            let res = await apiCall("guess", { guess });
            await refreshProfile();
            if (res.error) showToast(res.error, true);
            else if (res.win) setGameResult(`ЗНАК ${res.secret} ✦ ПОБЕДА +${res.message} ЭФИРА`);
            else setGameResult(`ЗНАК ${res.secret} ✦ ПУСТОТА ${res.message} ЭФИРА`);
            closeModal();
        });
    });
}

// 6. Монета
function gameCoinflip() {
    openModal("МОНЕТА", `<div class="rps-group">
        <button class="rps-btn" data-flip="орел">🪙 ОРЕЛ</button>
        <button class="rps-btn" data-flip="решка">🪙 РЕШКА</button>
    </div>`);
    document.querySelectorAll("#modalBody .rps-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let guess = btn.dataset.flip;
            let res = await apiCall("coinflip", { guess });
            await refreshProfile();
            if (res.error) showToast(res.error, true);
            else if (res.win) setGameResult(`${res.flip} ✦ ПОБЕДА +${res.message} ЭФИРА`);
            else setGameResult(`${res.flip} ✦ ПОРАЖЕНИЕ ${res.message} ЭФИРА`);
            closeModal();
        });
    });
}

// 7. Выше/Ниже
function gameHigher() {
    openModal("ВЫШЕ/НИЖЕ", `<div class="rps-group">
        <button class="rps-btn" data-guess="higher">📈 ВЫШЕ 7</button>
        <button class="rps-btn" data-guess="lower">📉 НИЖЕ 7</button>
    </div>`);
    document.querySelectorAll("#modalBody .rps-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let guess = btn.dataset.guess;
            let res = await apiCall("higher", { guess });
            await refreshProfile();
            if (res.error) showToast(res.error, true);
            else if (res.win) setGameResult(`КАРТА ${res.card} ✦ ПОБЕДА +${res.message} ЭФИРА`);
            else setGameResult(`КАРТА ${res.card} ✦ ПОРАЖЕНИЕ ${res.message} ЭФИРА`);
            closeModal();
        });
    });
}

// 8. Счастливый 7
function gameLucky7() {
    openModal("СЧАСТЛИВЫЙ 7", `<button class="slot-spin" id="luckyBtn">🎲 БРОСИТЬ (2 эфира)</button>`);
    document.getElementById("luckyBtn")?.addEventListener("click", async () => {
        let res = await apiCall("lucky7");
        await refreshProfile();
        if (res.error) showToast(res.error, true);
        else if (res.win) setGameResult(`${res.dice[0]}+${res.dice[1]}=7 ✦ ПОБЕДА +${res.message} ЭФИРА`);
        else setGameResult(`${res.dice[0]}+${res.dice[1]}=${res.dice[0]+res.dice[1]} ✦ ПОРАЖЕНИЕ ${res.message} ЭФИРА`);
        closeModal();
    });
}

// Привязка игр к карточкам
document.querySelectorAll(".game-card").forEach(card => {
    card.addEventListener("click", () => {
        let game = card.dataset.game;
        if (game === "dice1") gameDice1();
        else if (game === "dice2") gameDice2();
        else if (game === "rps") gameRPS();
        else if (game === "slots") gameSlots();
        else if (game === "guess") gameGuess();
        else if (game === "coinflip") gameCoinflip();
        else if (game === "higher") gameHigher();
        else if (game === "lucky7") gameLucky7();
    });
});

// ========== ПИТОМЦЫ ==========
async function loadPets() {
    let data = await apiCall("get_pets");
    let shopDiv = document.getElementById("shopPets");
    let myDiv = document.getElementById("myPets");
    if (!shopDiv || !myDiv) return;
    shopDiv.innerHTML = "";
    myDiv.innerHTML = "";
    for (let p of data.pets) {
        let card = `<div class="pet-card">
            <div>${p.emoji} ${p.name}</div>
            <div>💰 ${p.price} эфира</div>
            ${!p.owned ? `<button class="ritual-button buy-pet" data-id="${p.id}">ПРИЗВАТЬ</button>` : `<div>Уровень ${p.level}</div>`}
        </div>`;
        if (!p.owned) shopDiv.innerHTML += card;
        else myDiv.innerHTML += card;
    }
    document.querySelectorAll(".buy-pet").forEach(btn => {
        btn.addEventListener("click", async () => {
            let petId = parseInt(btn.dataset.id);
            let res = await apiCall("buy_pet", { pet_id: petId });
            if (res.success) {
                await refreshProfile();
                await loadPets();
                showToast(res.message);
            } else showToast(res.message, true);
        });
    });
}

// ========== АЛЬЯНСЫ ==========
async function loadAlliances() {
    let data = await apiCall("alliance_info");
    let panel = document.getElementById("alliancePanel");
    if (!panel) return;
    panel.innerHTML = `<div>Ваш альянс: ${data.alliance_id || "Нет"}</div>
    <button id="createAllianceBtn" class="ritual-button">СОЗДАТЬ АЛЬЯНС</button>
    <button id="joinAllianceBtn" class="ritual-button">ВСТУПИТЬ</button>`;
    let topDiv = document.getElementById("topAlliances");
    if (topDiv && data.top) {
        topDiv.innerHTML = data.top.map(t => `<div>🏛️ ${t[0]} — ${t[1]} эфира</div>`).join("");
    }
    document.getElementById("createAllianceBtn")?.addEventListener("click", () => {
        let name = prompt("Название альянса");
        let min = parseInt(prompt("Мин. монет для входа (0-100000)") || "0");
        apiCall("create_alliance", { name, min_coins: min }).then(res => {
            if (res.success) loadAlliances();
            else showToast("Ошибка", true);
        });
    });
    document.getElementById("joinAllianceBtn")?.addEventListener("click", () => {
        let id = parseInt(prompt("ID альянса"));
        apiCall("join_alliance", { alliance_id: id }).then(res => {
            if (res.success) loadAlliances();
            else showToast("Не удалось", true);
        });
    });
}

// ========== НАВИГАЦИЯ ==========
document.querySelectorAll(".nav-tab").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".nav-tab").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".dimension").forEach(d => d.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(btn.dataset.tab).classList.add("active");
        if (btn.dataset.tab === "pets") loadPets();
        if (btn.dataset.tab === "alliances") loadAlliances();
    });
});

refreshProfile();
loadPets();
loadAlliances();
