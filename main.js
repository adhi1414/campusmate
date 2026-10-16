const menuToggle = document.getElementById("menuToggle");
const navLinks = document.getElementById("navLinks");
if (menuToggle && navLinks) {
  menuToggle.addEventListener("click", () => navLinks.classList.toggle("open"));
}
document.querySelectorAll(".flash").forEach((item) => {
  window.setTimeout(() => item.classList.add("fade"), 6000);
});
