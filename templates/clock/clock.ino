// Full-screen 24h clock + 3-day forecast for Giga Display Shield (800x480)
// Sync via serial: "T HH:MM:SS YYYY-MM-DD\n" then "W <forecast_data>\n"
// Forecast format: "W day0_name,M_temp,M_code,N_temp,N_code,E_temp,E_code,Ni_temp,Ni_code|day1...|day2..."
// Touch anywhere in forecast area to toggle C/F.

#include "Arduino_GigaDisplay_GFX.h"
#include "Arduino_GigaDisplayTouch.h"
#include <Fonts/FreeSans24pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
#include <Fonts/FreeSans9pt7b.h>

GigaDisplay_GFX display;
Arduino_GigaDisplayTouch touch;

#define BG_COLOR    0x0000
#define FG_COLOR    0xC618  // light gray
#define BOX_COLOR   0x2945  // dark gray border
#define ICON_SUN    0xFDE0  // warm yellow
#define ICON_CLOUD  0x9CD3  // medium gray
#define ICON_RAIN   0x5D9F  // blue-ish
#define ICON_SNOW   0xFFFF  // white

static uint8_t cur_h = 0, cur_m = 0, cur_s = 0;
static int cur_year = 2025, cur_month = 1, cur_day = 1;
static unsigned long last_tick = 0;
static bool time_set = false;
static char prev_time[6] = "";

static bool use_fahrenheit = false;
static unsigned long last_touch = 0;

// Forecast data: 3 days x 4 periods
struct ForecastSlot {
  int temp;
  int code;
};

struct ForecastDay {
  char name[12];
  ForecastSlot slots[4]; // Morning, Noon, Evening, Night
};

static ForecastDay forecast[3];
static bool forecast_set = false;
static bool needs_redraw = true;

static const uint8_t days_in_month[] = {31,28,31,30,31,30,31,31,30,31,30,31};

static bool is_leap(int y) {
  return (y % 4 == 0 && y % 100 != 0) || (y % 400 == 0);
}

static uint8_t month_days(int y, int m) {
  uint8_t d = days_in_month[m - 1];
  if (m == 2 && is_leap(y)) d++;
  return d;
}

static void advance_date() {
  cur_day++;
  if (cur_day > month_days(cur_year, cur_month)) {
    cur_day = 1;
    cur_month++;
    if (cur_month > 12) { cur_month = 1; cur_year++; }
  }
}

void drawSun(int cx, int cy, int r) {
  display.fillCircle(cx, cy, r, ICON_SUN);
  for (int i = 0; i < 8; i++) {
    float angle = i * 3.14159f / 4.0f;
    int x1 = cx + cos(angle) * (r + 3);
    int y1 = cy + sin(angle) * (r + 3);
    int x2 = cx + cos(angle) * (r + 7);
    int y2 = cy + sin(angle) * (r + 7);
    display.drawLine(x1, y1, x2, y2, ICON_SUN);
  }
}

void drawCloud(int cx, int cy, uint16_t color) {
  display.fillCircle(cx - 8, cy, 7, color);
  display.fillCircle(cx + 4, cy, 9, color);
  display.fillCircle(cx + 14, cy + 2, 6, color);
  display.fillRect(cx - 14, cy, 28, 10, color);
}

void drawPartlyCloudy(int cx, int cy) {
  drawSun(cx - 4, cy - 5, 7);
  drawCloud(cx + 4, cy + 5, ICON_CLOUD);
}

void drawRain(int cx, int cy) {
  drawCloud(cx, cy - 5, ICON_CLOUD);
  for (int i = 0; i < 3; i++) {
    int dx = cx - 8 + i * 8;
    display.drawLine(dx, cy + 8, dx - 2, cy + 14, ICON_RAIN);
  }
}

void drawSnow(int cx, int cy) {
  drawCloud(cx, cy - 5, ICON_CLOUD);
  for (int i = 0; i < 3; i++) {
    int dx = cx - 6 + i * 7;
    display.fillCircle(dx, cy + 10, 2, ICON_SNOW);
  }
}

void drawWeatherIcon(int cx, int cy, int code) {
  if (code == 113) {
    drawSun(cx, cy, 10);
  } else if (code == 116) {
    drawPartlyCloudy(cx, cy);
  } else if (code == 119 || code == 122) {
    drawCloud(cx, cy, ICON_CLOUD);
  } else if (code >= 176 && code <= 263) {
    drawRain(cx, cy);
  } else if (code >= 227 && code <= 230) {
    drawSnow(cx, cy);
  } else if (code >= 293 && code <= 359) {
    drawRain(cx, cy);
  } else if (code >= 362 && code <= 395) {
    drawSnow(cx, cy);
  } else {
    drawCloud(cx, cy, ICON_CLOUD);
  }
}

int tempDisplay(int tempC) {
  if (use_fahrenheit) return tempC * 9 / 5 + 32;
  return tempC;
}

const char* tempUnit() {
  return use_fahrenheit ? "F" : "C";
}

void parseForecast(String &line) {
  String data = line.substring(2);
  int dayIdx = 0;
  int start = 0;

  while (dayIdx < 3 && start < (int)data.length()) {
    int pipePos = data.indexOf('|', start);
    String dayStr = (pipePos == -1) ? data.substring(start) : data.substring(start, pipePos);

    int pos = 0;
    int fieldIdx = 0;
    int fieldStart = 0;

    while (pos <= (int)dayStr.length() && fieldIdx < 9) {
      if (pos == (int)dayStr.length() || dayStr.charAt(pos) == ',') {
        String field = dayStr.substring(fieldStart, pos);
        if (fieldIdx == 0) {
          field.toCharArray(forecast[dayIdx].name, sizeof(forecast[dayIdx].name));
        } else {
          int slotIdx = (fieldIdx - 1) / 2;
          if (fieldIdx % 2 == 1) {
            forecast[dayIdx].slots[slotIdx].temp = field.toInt();
          } else {
            forecast[dayIdx].slots[slotIdx].code = field.toInt();
          }
        }
        fieldIdx++;
        fieldStart = pos + 1;
      }
      pos++;
    }

    dayIdx++;
    start = (pipePos == -1) ? data.length() : pipePos + 1;
  }

  forecast_set = true;
  needs_redraw = true;
}

void drawForecast() {
  if (!forecast_set) return;

  const char* periods[] = {"Morn", "Noon", "Eve", "Night"};

  int gridX = 20;
  int gridY = 80;
  int cellW = 185;
  int cellH = 90;
  int headerH = 25;
  int dayColW = 60;

  // Period headers
  display.setFont(&FreeSans9pt7b);
  display.setTextSize(1);
  display.setTextColor(FG_COLOR);
  for (int p = 0; p < 4; p++) {
    int x = gridX + dayColW + p * cellW + cellW / 2 - 15;
    display.setCursor(x, gridY + 15);
    display.print(periods[p]);
  }

  // Day rows
  for (int d = 0; d < 3; d++) {
    int rowY = gridY + headerH + d * cellH;

    // Day name
    display.setFont(&FreeSans9pt7b);
    display.setTextSize(1);
    display.setCursor(gridX + 2, rowY + cellH / 2 + 5);
    display.print(forecast[d].name);

    // Cells
    for (int p = 0; p < 4; p++) {
      int cellX = gridX + dayColW + p * cellW;

      display.drawRoundRect(cellX, rowY, cellW - 4, cellH - 4, 4, BOX_COLOR);

      int iconCx = cellX + cellW / 2 - 2;
      int iconCy = rowY + 30;
      drawWeatherIcon(iconCx, iconCy, forecast[d].slots[p].code);

      char tbuf[8];
      snprintf(tbuf, sizeof(tbuf), "%d%s", tempDisplay(forecast[d].slots[p].temp), tempUnit());
      display.setFont(&FreeSans9pt7b);
      display.setTextSize(1);
      display.setTextColor(FG_COLOR);
      int16_t x1, y1;
      uint16_t tw, th;
      display.getTextBounds(tbuf, 0, 0, &x1, &y1, &tw, &th);
      display.setCursor(iconCx - tw / 2, rowY + cellH - 12);
      display.print(tbuf);
    }
  }
}

void checkTouch() {
  GDTpoint_t points[5];
  uint8_t count = touch.getTouchPoints(points);
  if (count == 0) return;

  unsigned long now = millis();
  if (now - last_touch < 500) return; // debounce
  last_touch = now;

  // Touch coords are in native 480x800 (portrait).
  // Rotation 1 maps: display_x = touch_y, display_y = 479 - touch_x
  int disp_x = points[0].y;
  int disp_y = 479 - points[0].x;

  // Forecast area is roughly y > 70
  if (disp_y > 70) {
    use_fahrenheit = !use_fahrenheit;
    needs_redraw = true;
  }
}

void setup() {
  Serial.begin(115200);
  display.begin();
  display.setRotation(1);
  touch.begin();

  display.fillScreen(BG_COLOR);
  display.setFont(&FreeSans12pt7b);
  display.setTextColor(FG_COLOR);
  display.setTextSize(1);
  display.setCursor(250, 240);
  display.print("Waiting for time...");
}

void loop() {
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line.length() >= 10 && line.charAt(0) == 'T' && line.charAt(1) == ' ') {
      int h = line.substring(2, 4).toInt();
      int m = line.substring(5, 7).toInt();
      int s = line.substring(8, 10).toInt();
      if (h >= 0 && h < 24 && m >= 0 && m < 60 && s >= 0 && s < 60) {
        cur_h = h; cur_m = m; cur_s = s;
        last_tick = millis();
        if (line.length() >= 21) {
          cur_year = line.substring(11, 15).toInt();
          cur_month = line.substring(16, 18).toInt();
          cur_day = line.substring(19, 21).toInt();
        }
        if (!time_set) { time_set = true; needs_redraw = true; }
        prev_time[0] = '\0';
      }
    } else if (line.length() > 2 && line.charAt(0) == 'W' && line.charAt(1) == ' ') {
      parseForecast(line);
    }
  }

  if (!time_set) return;

  checkTouch();

  // Advance clock
  unsigned long now = millis();
  unsigned long elapsed = now - last_tick;
  if (elapsed >= 1000) {
    unsigned long secs = elapsed / 1000;
    last_tick += secs * 1000;
    for (unsigned long i = 0; i < secs; i++) {
      cur_s++;
      if (cur_s >= 60) { cur_s = 0; cur_m++; }
      if (cur_m >= 60) { cur_m = 0; cur_h++; }
      if (cur_h >= 24) { cur_h = 0; advance_date(); }
    }
  }

  char time_buf[6];
  snprintf(time_buf, sizeof(time_buf), "%02d:%02d", cur_h, cur_m);

  bool time_changed = (strcmp(time_buf, prev_time) != 0);

  if (!time_changed && !needs_redraw) return;

  if (needs_redraw) {
    display.fillScreen(BG_COLOR);
    drawForecast();
    needs_redraw = false;
  } else {
    display.fillRect(15, 5, 250, 55, BG_COLOR);
  }

  // Time - upper left
  display.setFont(&FreeSans24pt7b);
  display.setTextSize(1);
  display.setTextColor(FG_COLOR);
  display.setCursor(20, 50);
  display.print(time_buf);

  // Date - upper right
  char date_buf[12];
  snprintf(date_buf, sizeof(date_buf), "%04d-%02d-%02d", cur_year, cur_month, cur_day);
  display.setFont(&FreeSans12pt7b);
  display.setTextSize(1);
  int16_t x1, y1;
  uint16_t tw, th;
  display.getTextBounds(date_buf, 0, 0, &x1, &y1, &tw, &th);
  display.setCursor(780 - tw, 45);
  display.print(date_buf);

  strcpy(prev_time, time_buf);
}
