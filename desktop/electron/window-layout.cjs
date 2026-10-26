// Tiling has no portable OS flag. Match a full-height left/right work-area tile;
// a narrow floating window and a maximized/fullscreen window do not qualify.
function isSplitLayout(bounds, area) {
  const tolerance = 16;
  return area.width > 0 && area.height > 0 && bounds.width <= area.width * .8
    && Math.abs(bounds.y - area.y) <= tolerance
    && Math.abs(bounds.height - area.height) <= tolerance
    && (Math.abs(bounds.x - area.x) <= tolerance
      || Math.abs(bounds.x + bounds.width - area.x - area.width) <= tolerance);
}
module.exports = { isSplitLayout };
