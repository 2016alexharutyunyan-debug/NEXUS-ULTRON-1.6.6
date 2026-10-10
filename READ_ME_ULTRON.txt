NEXUS ULTRON 1.6.6 - RELIABLE AIR TYPING AND PALM BACKSPACE

START
1. Close the older NEXUS completely from its system-tray Exit NEXUS command.
2. Double-click START_NEXUS.bat.
(No new packages are needed. New files: payload\gesture_engine.py and payload\gesture_overlay.py.)

VOICE
- ULTRON is the only voice assistant. Say "Hey Ultron" or a direct command such as "Open browser".
- Commands now match whole words only ("phone" no longer fires inside "microphone").

AIR TYPING (both palms open -> Windows On-Screen Keyboard -> type with all ten fingers)
1. Hold both open palms toward the camera for about half a second. NEXUS opens the real Windows keyboard.
2. Keep both hands in view. AIR TYPING mode starts: you will see a dot on the keyboard for every fingertip
   (yellow = left side hand, green = right side hand, bigger dot = index finger).
3. Move a hand so a dot sits over the key you want, then make a short tap with THAT finger
   (a quick bend). A white ring flashes where the key was pressed.
4. You do NOT need to lower a hand any more and open palms no longer block typing.
   Resting both open palms does not re-open or move the keyboard while it is already open.
5. The mouse is NOT frozen while you type:
   - A key press moves the pointer onto the key and puts it back where it was a moment later.
   - Typing hands never push the pointer around. To move the mouse while the keyboard is open, POINT with
     one hand (index finger up, the other three fingers curled); pinch with that hand to click, e.g. to
     choose the text field you want to type into.
   - Take one hand out of view for about 1.5 seconds to return to the normal cursor mode.
6. Tuning:
   - Control Center -> "Air-typing sensitivity" slider (higher = lighter taps count).
   - If the dots sit too high/low on the keyboard, edit %APPDATA%\HoloDeskAI\settings.json:
     kb_map_y0 / kb_map_y1 (which part of the camera view is the keyboard, top..bottom) and
     kb_map_x0 / kb_map_x1 (left..right). Smaller kb_map_y0 = hands can be held higher.
   - Good light and hands 40-70 cm from the camera give the best results.
7. Reading the dots: a dot GROWS and turns RED while its finger bends. If dots never grow when you tap,
   raise the sensitivity slider. If they turn red but nothing is typed, look at the toast / log below.
8. Messages at the bottom of the screen:
   "AIR TYPING"                      typing mode is on
   "Show BOTH hands ..."             keyboard is open but only one hand is visible
   "Keyboard window not detected"    osk.exe did not appear - open it manually once (Win+Ctrl+O)
   "KEY PRESS FAILED: ..."           Windows refused the click (see reason; Administrator apps need NEXUS as Admin)
9. Diagnostic log (send it to me if something does not work):
   %APPDATA%\HoloDeskAI\air_typing.log

PALM BACKSPACE (delete the last character or the selected text)
- Rest one open palm low in the camera view for a moment, then swipe it UP quickly. One Backspace is sent
  to the focused application ("BACKSPACE" appears at the bottom of the screen).
- The mouse pointer is put back where it was when the swipe started and follows your hand again right away.
- Lower the hand before swiping again.
- A hand that is simply raised into view without a pause is ignored on purpose (settings.json
  palm_swipe_dwell = 0.10; set 0 to allow it).
- Works while the keyboard is open (a longer swipe is required then) and when NEXUS is minimised.
- If the focused program runs as Administrator, run NEXUS as Administrator too, otherwise Windows blocks
  the key press.

OTHER FIXES IN 1.6.6
- Phone companion: long random token, constant-time check, temporary block after repeated wrong tokens.
- Gemini key is sent in a header instead of the URL.
- Faster hand tracking (30 Hz) while air typing; cheaper keyboard lookup.
- Open-palm detection no longer depends on absolute finger spread or hand rotation.

COMPATIBILITY
Some internal filenames and JARVIS_* setting names are retained so older installs and saved settings
continue to work. They do not change ULTRON's visible or spoken identity.
