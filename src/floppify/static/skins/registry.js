/* Global Floppify skin registry.
 *
 * To add a skin: create /static/skins/<id>.css, then add its metadata here.
 * Layout and appearance belong in the skin CSS; playback behavior stays in app.js.
 */
window.FLOPPIFY_SKINS = Object.freeze([
  Object.freeze({
    id: "spotify",
    label: "Floppify Green",
    stylesheet: "/static/skins/spotify.css?v=skin-2",
    themeColor: "#070707",
  }),
  Object.freeze({
    id: "winamp98",
    label: "Winamp 98",
    stylesheet: "/static/skins/winamp98.css?v=skin-3",
    themeColor: "#008080",
  }),
]);
