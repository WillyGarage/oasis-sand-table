// Protected by the same lock as the queue: clients can see either revision, never half a scene.
// Starting fresh after a restart is intentional; the last power loss may have occurred mid-stroke.
struct GuestState {
  uint32_t rev;
  bool known, photo, evolving;
  volatile bool pending;
  char slots[3][41];
};
GuestState guestState = {};
char nextGuestSlots[3][41] = {};
bool nextGuestIsScene = false;
uint32_t guestHoldS = 300, guestNextMs = 0;
struct GuestThemes {
  char id[3][8][32];
  uint8_t count[3];
};
GuestThemes guestThemes = {};  // The web task owns the choices; the motion task only changes evolving and the deadline.
void stopGuestEvolution() {
  portENTER_CRITICAL(&stepMux);
  if (guestState.evolving) { guestState.evolving = false; guestState.rev++; }
  portEXIT_CRITICAL(&stepMux);
}

void forgetGuestLocked() {
  guestState.evolving = false;
  guestState.known = false;
  guestState.photo = false;
  guestState.pending = false;
  memset(guestState.slots, 0, sizeof guestState.slots);
  guestState.rev++;
}
void forgetGuest() {
  portENTER_CRITICAL(&stepMux);
  forgetGuestLocked();
  portEXIT_CRITICAL(&stepMux);
}
void finishGuest() {
  portENTER_CRITICAL(&stepMux);
  if (guestState.pending) {
    memcpy(guestState.slots, nextGuestSlots, sizeof guestState.slots);
    guestState.known = nextGuestIsScene;
    guestState.photo = !nextGuestIsScene;
    if (guestState.evolving) guestNextMs = millis() + guestHoldS * 1000U;
    guestState.pending = false;
    guestState.rev++;
  }
  portEXIT_CRITICAL(&stepMux);
}
