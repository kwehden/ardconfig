// ardconfig verification sketch
// LED pin resolved from board profile or LED_BUILTIN
#ifndef ARDCONFIG_LED_PIN
#define ARDCONFIG_LED_PIN LED_BUILTIN
#endif

void setup() {
  pinMode(ARDCONFIG_LED_PIN, OUTPUT);
  Serial.begin(115200);
  Serial.println("ardconfig: verify OK");
}

void loop() {
  digitalWrite(ARDCONFIG_LED_PIN, HIGH);
  delay(500);
  digitalWrite(ARDCONFIG_LED_PIN, LOW);
  delay(500);
}
