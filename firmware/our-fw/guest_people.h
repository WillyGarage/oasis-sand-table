// The web task owns this small, local guest book. A guest can add an interest while
// the table draws. Save it to LittleFS as soon as the flash is free.
struct GuestPerson { String name, interest, subject; };
const int MAX_GUESTS = 48;
GuestPerson people[MAX_GUESTS];
int numPeople = 0;
uint32_t peopleRev = 0, nextPeopleSave = 0;
bool peopleDirty = false;

bool guestText(const String& value, size_t limit) {
  if (!value.length() || value.length() > limit) return false;
  for (unsigned i = 0; i < value.length(); i++) if ((unsigned char)value[i] < 32) return false;
  return true;
}
String guestQuoted(const String& value) {
  String out = "\"";
  for (unsigned i = 0; i < value.length(); i++) {
    char c = value[i];
    if (c == '"' || c == '\\') out += '\\';
    out += c;
  }
  return out + "\"";
}
void loadPeople() {
  peopleRev = esp_random();
  if (!fsOk || !LittleFS.exists("/guest-people.txt")) return;
  File f = LittleFS.open("/guest-people.txt", "r");
  while (f && f.available() && numPeople < MAX_GUESTS) {
    String row = f.readStringUntil('\n');
    int a = row.indexOf('\t'), b = row.indexOf('\t', a + 1);
    if (a <= 0 || b <= a + 1) continue;
    people[numPeople++] = {row.substring(0,a), row.substring(a+1,b), row.substring(b+1)};
  }
}
void savePeopleWhenIdle() {
  if (!peopleDirty || busy() || stepN || (int32_t)(millis() - nextPeopleSave) < 0 || !flashBegin()) return;
  File f = LittleFS.open("/guest-people.tmp", "w");
  bool ok = (bool)f;
  for (int i=0; ok && i<numPeople; i++) {
    const GuestPerson& p = people[i];
    String row = p.name + "\t" + p.interest + "\t" + p.subject + "\n";
    ok = f.print(row) == row.length();
  }
  f.close();
  if (ok) ok = LittleFS.rename("/guest-people.tmp", "/guest-people.txt");
  flashEnd();
  peopleDirty = !ok;
  nextPeopleSave = millis() + 5000;
}
void guestPeopleReply() {
  String out = "{\"rev\":\"" + String((unsigned long)peopleRev) + "\",\"people\":[";
  for (int i=0; i<numPeople; i++) {
    const GuestPerson& p = people[i];
    if (i) out += ",";
    out += "{\"name\":" + guestQuoted(p.name) + ",\"interest\":" + guestQuoted(p.interest) +
           ",\"subject\":" + guestQuoted(p.subject) + "}";
  }
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json", out + "]}");
}
void guestPersonUpdate() {
  if (!fsOk) { reply(503, "Guest storage unavailable."); return; }
  String name = server.arg("name"), interest = server.arg("interest"), subject = server.arg("subject");
  name.trim(); interest.trim();
  if (!guestText(name,128) || !guestText(interest,400) || subject.length() > 40) {
    reply(400, "Enter a name and a short interest."); return;
  }
  for (unsigned i=0; i<subject.length(); i++) {
    char c = subject[i];
    if (!(isalnum((unsigned char)c) || c=='-' || c=='_')) { reply(400,"Invalid subject."); return; }
  }
  int i = 0;
  while (i < numPeople && !people[i].name.equalsIgnoreCase(name)) i++;
  if (i == MAX_GUESTS) { reply(409, "The guest book is full."); return; }
  if (i == numPeople || people[i].name != name || people[i].interest != interest || people[i].subject != subject) {
    if (i == numPeople) numPeople++;
    people[i] = {name,interest,subject};
    peopleRev++;
    peopleDirty = true;
    nextPeopleSave = millis();
    savePeopleWhenIdle();
  }
  guestPeopleReply();
}
