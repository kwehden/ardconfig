#include <Wire.h>

void setup() {
  Wire.begin();
  Serial.begin(115200);
  while (!Serial);

  Serial.println("ardconfig: I2C scan");
  Serial.println("Scanning addresses 0x01-0x7F...");

  uint8_t found = 0;
  for (uint8_t addr = 1; addr < 128; addr++) {
    Wire.beginTransmission(addr);
    uint8_t err = Wire.endTransmission();
    if (err == 0) {
      Serial.print("  [FOUND] 0x");
      if (addr < 16) Serial.print("0");
      Serial.print(addr, HEX);
      Serial.print(" (");
      Serial.print(addr);
      Serial.println(")");
      found++;
    }
  }

  if (found == 0) {
    Serial.println("  No I2C devices found.");
  } else {
    Serial.print("  Total: ");
    Serial.print(found);
    Serial.println(" device(s).");
  }
  Serial.println("Done.");
}

void loop() {}
