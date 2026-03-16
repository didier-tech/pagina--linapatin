const btn = document.getElementById("mobileBtn");
const menu = document.getElementById("navMenu");

btn.onclick = function () {
    if (menu.style.display === "flex") {
        menu.style.display = "none";
    } else {
        menu.style.display = "flex";
    }
};


let slides = document.querySelectorAll(".hero-slide");
let current = 0;

function showSlide(index) {
    slides.forEach(s => s.classList.remove("active"));
    slides[index].classList.add("active");
}

function nextSlide() {
    current = (current + 1) % slides.length;
    showSlide(current);
}

function prevSlide() {
    current = (current - 1 + slides.length) % slides.length;
    showSlide(current);
}

if (slides.length > 0) {
    showSlide(current);
    setInterval(nextSlide, 6000);

    document.querySelector(".hero-btn.next").onclick = nextSlide;
    document.querySelector(".hero-btn.prev").onclick = prevSlide;
}
