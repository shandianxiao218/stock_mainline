/*
 * eastmoney_import.c - 东方财富本地日线数据导入器
 *
 * 读取东方财富客户端二进制日线文件，不依赖 Python 解析 .dat。
 *
 * 构建：
 *   gcc -O2 -std=c11 -Wall -Wextra -o tools/eastmoney_import.exe tools/eastmoney_import.c
 *
 * 用法：
 *   tools\eastmoney_import.exe [eastmoney_root] [output_dir] [start_date]
 *
 * 默认：
 *   eastmoney_root = C:\eastmoney
 *   output_dir     = backend\data\eastmoney
 *   start_date     = 20200101
 *
 * 输出：
 *   stocks.csv       symbol,name,market,last_date,last_close,last_volume,total_bars
 *   daily_quotes.csv symbol,date,open,high,low,close,volume,amount
 *   sector_constituents.csv sector_code,sector_name,source,symbol,market,as_of_date
 */

#define _CRT_SECURE_NO_WARNINGS

#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#define EM_ENTRY_SIZE 516
#define EM_RECORD_SIZE 40
#define EM_FILE_HEADER_SIZE 48
#define EM_BLOCK_ID_OFFSET 32
#define EM_MAX_STOCKS 12000
#define EM_MAX_NAME 64
#define PATH_BUF_SIZE 1024

#pragma pack(push, 1)
typedef struct {
    uint32_t date;
    uint32_t reserved;
    float open;
    float close;
    float high;
    float low;
    uint32_t volume;
    uint32_t reserved2;
    double amount;
} EMRecord;

typedef struct {
    char code[16];
    uint8_t reserved[8];
    uint32_t total_days;
    uint32_t reserved2;
    uint32_t block_ids[121];
} EMEntry;
#pragma pack(pop)

typedef struct {
    char symbol[8];
    char name[EM_MAX_NAME];
    char market[4];
    uint32_t total_days;
    uint32_t entry_offset;
    uint32_t last_date;
    double last_close;
    uint32_t last_volume;
    int total_bars;
} StockInfo;

#define NAME_MAP_SIZE 16384
typedef struct NameEntry {
    char code[8];
    char name[EM_MAX_NAME];
    struct NameEntry *next;
} NameEntry;

static NameEntry *g_name_map[NAME_MAP_SIZE];
static char g_progress_path[PATH_BUF_SIZE];

static unsigned name_hash(const char *code) {
    unsigned h = 5381;
    while (*code) h = h * 33u + (unsigned char)*code++;
    return h & (NAME_MAP_SIZE - 1);
}

static void name_map_set(const char *code, const char *name) {
    unsigned h = name_hash(code);
    NameEntry *entry = (NameEntry *)malloc(sizeof(NameEntry));
    if (!entry) return;
    strncpy(entry->code, code, sizeof(entry->code) - 1);
    entry->code[sizeof(entry->code) - 1] = '\0';
    strncpy(entry->name, name, sizeof(entry->name) - 1);
    entry->name[sizeof(entry->name) - 1] = '\0';
    entry->next = g_name_map[h];
    g_name_map[h] = entry;
}

static const char *name_map_get(const char *code) {
    unsigned h = name_hash(code);
    NameEntry *entry = g_name_map[h];
    while (entry) {
        if (strcmp(entry->code, code) == 0) return entry->name;
        entry = entry->next;
    }
    return NULL;
}

static void name_map_free(void) {
    for (int i = 0; i < NAME_MAP_SIZE; i++) {
        NameEntry *entry = g_name_map[i];
        while (entry) {
            NameEntry *next = entry->next;
            free(entry);
            entry = next;
        }
        g_name_map[i] = NULL;
    }
}

static int get_file_size64(HANDLE file, uint64_t *size) {
    DWORD high = 0;
    DWORD low = GetFileSize(file, &high);
    if (low == INVALID_FILE_SIZE && GetLastError() != NO_ERROR) return 0;
    *size = ((uint64_t)high << 32) | low;
    return 1;
}

static void path_join(char *out, size_t out_size, const char *left, const char *right) {
    size_t len = strlen(left);
    snprintf(out, out_size, "%s%s%s", left, (len > 0 && (left[len - 1] == '\\' || left[len - 1] == '/')) ? "" : "\\", right);
}

static void ensure_dir(const char *path) {
    char buf[PATH_BUF_SIZE];
    size_t len = strlen(path);
    if (len >= sizeof(buf)) return;
    strcpy(buf, path);
    for (char *p = buf; *p; p++) {
        if (*p == '/' || *p == '\\') {
            char old = *p;
            *p = '\0';
            if (strlen(buf) > 2) CreateDirectoryA(buf, NULL);
            *p = old;
        }
    }
    CreateDirectoryA(buf, NULL);
}

static void write_progress(const char *phase, const char *market, long current, long total, const char *message) {
    FILE *f = fopen(g_progress_path, "w");
    if (!f) return;
    fprintf(f, "{\"phase\":\"%s\",\"market\":\"%s\",\"current\":%ld,\"total\":%ld,\"message\":\"%s\"}\n",
            phase, market ? market : "", current, total, message ? message : "");
    fclose(f);
}

static int is_a_share_code(const char *code, const char *market) {
    if (strlen(code) != 6) return 0;
    for (int i = 0; i < 6; i++) {
        if (!isdigit((unsigned char)code[i])) return 0;
    }
    if (strcmp(market, "SH") == 0) {
        return strncmp(code, "600", 3) == 0 ||
               strncmp(code, "601", 3) == 0 ||
               strncmp(code, "603", 3) == 0 ||
               strncmp(code, "605", 3) == 0 ||
               strncmp(code, "688", 3) == 0 ||
               strncmp(code, "689", 3) == 0;
    }
    if (strcmp(market, "SZ") == 0) {
        return strncmp(code, "000", 3) == 0 ||
               strncmp(code, "001", 3) == 0 ||
               strncmp(code, "002", 3) == 0 ||
               strncmp(code, "003", 3) == 0 ||
               strncmp(code, "300", 3) == 0 ||
               strncmp(code, "301", 3) == 0;
    }
    return 0;
}

static int valid_em_date(uint32_t date) {
    int year = (int)(date / 10000);
    int month = (int)((date / 100) % 100);
    int day = (int)(date % 100);
    return year >= 1990 && year <= 2035 && month >= 1 && month <= 12 && day >= 1 && day <= 31;
}

static int map_file_readonly(const char *path, HANDLE *file, HANDLE *map, char **view, uint64_t *size) {
    *file = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (*file == INVALID_HANDLE_VALUE) return 0;
    if (!get_file_size64(*file, size)) {
        CloseHandle(*file);
        return 0;
    }
    *map = CreateFileMappingA(*file, NULL, PAGE_READONLY, 0, 0, NULL);
    if (!*map) {
        CloseHandle(*file);
        return 0;
    }
    *view = (char *)MapViewOfFile(*map, FILE_MAP_READ, 0, 0, 0);
    if (!*view) {
        CloseHandle(*map);
        CloseHandle(*file);
        return 0;
    }
    return 1;
}

static void unmap_file(HANDLE file, HANDLE map, char *view) {
    if (view) UnmapViewOfFile(view);
    if (map) CloseHandle(map);
    if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
}

static void build_name_table(const char *name_file) {
    HANDLE file = INVALID_HANDLE_VALUE;
    HANDLE map = NULL;
    char *mm = NULL;
    uint64_t file_size64 = 0;
    if (!map_file_readonly(name_file, &file, &map, &mm, &file_size64)) return;

    size_t file_size = (size_t)file_size64;
    for (size_t i = 0; i + 6 <= file_size; i++) {
        unsigned char c = (unsigned char)mm[i];
        if (c < '0' || c > '6') continue;
        int ok = 1;
        for (int d = 1; d < 6; d++) {
            if (!isdigit((unsigned char)mm[i + d])) {
                ok = 0;
                break;
            }
        }
        if (!ok) continue;
        if (i > 0 && isdigit((unsigned char)mm[i - 1])) continue;
        if (i + 6 < file_size && isdigit((unsigned char)mm[i + 6])) continue;

        char code[7];
        memcpy(code, mm + i, 6);
        code[6] = '\0';
        if (name_map_get(code)) {
            i += 5;
            continue;
        }

        if (i < 120) {
            i += 5;
            continue;
        }
        const char *window_start = mm + i - 120;
        int best_score = 0;
        char best_name[EM_MAX_NAME];
        best_name[0] = '\0';
        for (const char *p = window_start; p < mm + i; p++) {
            if (*p != 0) continue;
            const char *seg = p + 1;
            while (seg > window_start && *(seg - 1) != 0) seg--;
            int len = (int)(p - seg);
            if (len >= 4 && len <= 24) {
                int high_bytes = 0;
                for (int j = 0; j < len; j++) {
                    if ((unsigned char)seg[j] >= 0x80) high_bytes++;
                }
                if (high_bytes >= len / 2) {
                    int score = high_bytes * 4 + len;
                    if (score > best_score) {
                        best_score = score;
                        memcpy(best_name, seg, (size_t)len);
                        best_name[len] = '\0';
                    }
                }
            }
        }
        if (best_name[0]) name_map_set(code, best_name);
        i += 5;
    }

    unmap_file(file, map, mm);
}

static int scan_market_file(const char *day_file, const char *market, StockInfo **stocks_out) {
    HANDLE file = INVALID_HANDLE_VALUE;
    HANDLE map = NULL;
    char *mm = NULL;
    uint64_t file_size = 0;
    if (!map_file_readonly(day_file, &file, &map, &mm, &file_size)) return 0;

    uint32_t capacity = *(uint32_t *)(mm + 20);
    StockInfo *stocks = (StockInfo *)calloc(EM_MAX_STOCKS, sizeof(StockInfo));
    if (!stocks) {
        unmap_file(file, map, mm);
        return 0;
    }

    int stock_count = 0;
    for (uint32_t slot = 0; slot < capacity && stock_count < EM_MAX_STOCKS; slot++) {
        if (slot % 500 == 0) write_progress("scanning", market, (long)slot, (long)capacity, "扫描股票目录");
        uint32_t entry_offset = EM_FILE_HEADER_SIZE + slot * EM_ENTRY_SIZE;
        if ((uint64_t)entry_offset + EM_ENTRY_SIZE > file_size) break;

        EMEntry *entry = (EMEntry *)(mm + entry_offset);
        char code[17];
        memcpy(code, entry->code, 16);
        code[16] = '\0';
        char *nul = (char *)memchr(code, '\0', 16);
        if (nul) *nul = '\0';

        if (!is_a_share_code(code, market)) continue;
        if (entry->total_days == 0) continue;

        StockInfo *stock = &stocks[stock_count++];
        strncpy(stock->symbol, code, sizeof(stock->symbol) - 1);
        strncpy(stock->market, market, sizeof(stock->market) - 1);
        stock->total_days = entry->total_days;
        stock->entry_offset = entry_offset;
        const char *name = name_map_get(code);
        strncpy(stock->name, name && name[0] ? name : code, sizeof(stock->name) - 1);
    }

    unmap_file(file, map, mm);
    *stocks_out = stocks;
    return stock_count;
}

static void csv_text(FILE *f, const char *text) {
    fputc('"', f);
    for (const char *p = text; p && *p; p++) {
        if (*p == '"') fputc('"', f);
        fputc(*p, f);
    }
    fputc('"', f);
}

static void gbk_to_utf8(const char *input, char *output, int output_size) {
    if (!input || !*input || output_size <= 0) {
        if (output_size > 0) output[0] = '\0';
        return;
    }
    wchar_t wide[512];
    int wide_len = MultiByteToWideChar(936, 0, input, -1, wide, (int)(sizeof(wide) / sizeof(wide[0])));
    if (wide_len <= 0) {
        strncpy(output, input, (size_t)output_size - 1);
        output[output_size - 1] = '\0';
        return;
    }
    int utf8_len = WideCharToMultiByte(CP_UTF8, 0, wide, -1, output, output_size, NULL, NULL);
    if (utf8_len <= 0) output[0] = '\0';
}

static int member_to_symbol(const char *token, char *symbol, char *market) {
    if (!token || strlen(token) < 8) return 0;
    if (!(token[0] == '0' || token[0] == '1')) return 0;
    if (token[1] != '.') return 0;
    for (int i = 0; i < 6; i++) {
        if (!isdigit((unsigned char)token[i + 2])) return 0;
        symbol[i] = token[i + 2];
    }
    symbol[6] = '\0';
    strcpy(market, token[0] == '1' ? "SH" : "SZ");
    return is_a_share_code(symbol, market);
}

static int export_sector_constituents(const char *sector_file, const char *output_path) {
    FILE *in = fopen(sector_file, "rb");
    if (!in) return 0;
    FILE *out = fopen(output_path, "wb");
    if (!out) {
        fclose(in);
        return 0;
    }
    fprintf(out, "sector_code,sector_name,source,symbol,market,as_of_date\n");
    static char line[2 * 1024 * 1024];
    int written = 0;
    while (fgets(line, sizeof(line), in)) {
        char *fields[7] = {0};
        char *cursor = line;
        int field_count = 0;
        while (field_count < 6) {
            fields[field_count++] = cursor;
            char *sep = strchr(cursor, ';');
            if (!sep) break;
            *sep = '\0';
            cursor = sep + 1;
        }
        if (field_count < 6 || !fields[1] || strncmp(fields[1], "90.BK", 5) != 0) continue;
        fields[6] = cursor;
        char *members = fields[6];
        if (!members || !*members) continue;
        char *newline = strpbrk(members, "\r\n");
        if (newline) *newline = '\0';

        char sector_name_utf8[512];
        gbk_to_utf8(fields[5], sector_name_utf8, sizeof(sector_name_utf8));

        char *token = strtok(members, ",:");
        while (token) {
            char symbol[8];
            char market[4];
            if (member_to_symbol(token, symbol, market)) {
                csv_text(out, fields[1]);
                fputc(',', out);
                csv_text(out, sector_name_utf8);
                fprintf(out, ",eastmoney_hs_bk,%s,%s,\n", symbol, market);
                written++;
            }
            token = strtok(NULL, ",:");
        }
    }
    fclose(out);
    fclose(in);
    return written;
}

static int import_market_data(const char *day_file, const char *market, StockInfo *stocks, int stock_count, FILE *quotes_csv, uint32_t start_date) {
    HANDLE file = INVALID_HANDLE_VALUE;
    HANDLE map = NULL;
    char *mm = NULL;
    uint64_t file_size = 0;
    if (!map_file_readonly(day_file, &file, &map, &mm, &file_size)) return 0;

    uint32_t capacity = *(uint32_t *)(mm + 20);
    uint32_t records_per_block = *(uint32_t *)(mm + 16);
    if (records_per_block == 0) records_per_block = 400;
    uint32_t data_start = EM_FILE_HEADER_SIZE + capacity * EM_ENTRY_SIZE;
    uint32_t block_size = records_per_block * EM_RECORD_SIZE;
    int written = 0;

    for (int i = 0; i < stock_count; i++) {
        if (i % 100 == 0) write_progress("importing", market, i, stock_count, "导出日线CSV");
        StockInfo *stock = &stocks[i];
        if (stock->entry_offset < EM_FILE_HEADER_SIZE || stock->entry_offset + EM_ENTRY_SIZE > data_start) continue;

        EMEntry *entry = (EMEntry *)(mm + stock->entry_offset);
        uint32_t block_count = (EM_ENTRY_SIZE - EM_BLOCK_ID_OFFSET) / 4;
        uint32_t used_blocks = (entry->total_days + records_per_block - 1) / records_per_block;
        if (used_blocks > block_count) used_blocks = block_count;

        for (uint32_t bi = 0; bi < used_blocks; bi++) {
            uint32_t block_id = entry->block_ids[bi];
            if (block_id == 0xFFFFFFFF) continue;
            uint64_t block_offset = (uint64_t)data_start + (uint64_t)block_id * block_size;
            if (block_offset + block_size > file_size) continue;

            uint32_t rows_in_block = records_per_block;
            if (bi == used_blocks - 1 && entry->total_days % records_per_block) {
                rows_in_block = entry->total_days % records_per_block;
            }

            for (uint32_t ri = 0; ri < rows_in_block; ri++) {
                EMRecord *rec = (EMRecord *)(mm + block_offset + ri * EM_RECORD_SIZE);
                if (!valid_em_date(rec->date)) continue;
                if (rec->date < start_date) continue;
                if (rec->open <= 0 || rec->close <= 0) continue;

                fprintf(quotes_csv, "%s,%u,%.4f,%.4f,%.4f,%.4f,%u,%.2f\n",
                        stock->symbol,
                        rec->date,
                        rec->open,
                        rec->high,
                        rec->low,
                        rec->close,
                        rec->volume,
                        rec->amount);
                written++;
                stock->last_date = rec->date;
                stock->last_close = rec->close;
                stock->last_volume = rec->volume;
                stock->total_bars++;
            }
        }
    }

    unmap_file(file, map, mm);
    return written;
}

static void write_stocks_csv(const char *path, StockInfo *stocks, int count) {
    FILE *f = fopen(path, "wb");
    if (!f) return;
    fprintf(f, "symbol,name,market,last_date,last_close,last_volume,total_bars\n");
    for (int i = 0; i < count; i++) {
        fprintf(f, "%s,", stocks[i].symbol);
        csv_text(f, stocks[i].name);
        fprintf(f, ",%s,%u,%.4f,%u,%d\n",
                stocks[i].market,
                stocks[i].last_date,
                stocks[i].last_close,
                stocks[i].last_volume,
                stocks[i].total_bars);
    }
    fclose(f);
}

static int file_exists(const char *path) {
    DWORD attrs = GetFileAttributesA(path);
    return attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY);
}

static void find_name_file(char *out, size_t out_size, const char *root, const char *file_name) {
    char rel[PATH_BUF_SIZE];
    snprintf(rel, sizeof(rel), "swc8\\data\\StkQuoteList\\%s", file_name);
    path_join(out, out_size, root, rel);
    if (file_exists(out)) return;
    snprintf(rel, sizeof(rel), "swc8\\data\\StkQuoteListNsl\\%s", file_name);
    path_join(out, out_size, root, rel);
}

int main(int argc, char **argv) {
    const char *eastmoney_root = argc >= 2 ? argv[1] : "C:\\eastmoney";
    const char *output_dir = argc >= 3 ? argv[2] : "backend\\data\\eastmoney";
    uint32_t start_date = argc >= 4 ? (uint32_t)atoi(argv[3]) : 20200101;

    ensure_dir(output_dir);
    path_join(g_progress_path, sizeof(g_progress_path), output_dir, "eastmoney_import.progress.json");
    write_progress("init", "", 0, 1, "初始化东方财富导入器");

    char sh_day_file[PATH_BUF_SIZE];
    char sz_day_file[PATH_BUF_SIZE];
    char sh_name_file[PATH_BUF_SIZE];
    char sz_name_file[PATH_BUF_SIZE];
    char quotes_path[PATH_BUF_SIZE];
    char stocks_path[PATH_BUF_SIZE];
    char sector_file[PATH_BUF_SIZE];
    char sector_path[PATH_BUF_SIZE];

    path_join(sh_day_file, sizeof(sh_day_file), eastmoney_root, "swc8\\data\\SHANGHAI\\DayData_SH_V43.dat");
    path_join(sz_day_file, sizeof(sz_day_file), eastmoney_root, "swc8\\data\\SHENZHEN\\DayData_SZ_V43.dat");
    find_name_file(sh_name_file, sizeof(sh_name_file), eastmoney_root, "StkQuoteList_V10_1.dat");
    find_name_file(sz_name_file, sizeof(sz_name_file), eastmoney_root, "StkQuoteList_V10_0.dat");
    path_join(quotes_path, sizeof(quotes_path), output_dir, "daily_quotes.csv");
    path_join(stocks_path, sizeof(stocks_path), output_dir, "stocks.csv");
    path_join(sector_file, sizeof(sector_file), eastmoney_root, "swc8\\data\\hs_bk_crc_data_new.dat");
    path_join(sector_path, sizeof(sector_path), output_dir, "sector_constituents.csv");

    if (!file_exists(sh_day_file) || !file_exists(sz_day_file)) {
        fprintf(stderr, "东方财富日线文件不存在：%s 或 %s\n", sh_day_file, sz_day_file);
        write_progress("error", "", 0, 1, "东方财富日线文件不存在");
        return 2;
    }

    write_progress("names", "", 0, 2, "构建股票名称索引");
    build_name_table(sh_name_file);
    build_name_table(sz_name_file);

    StockInfo *sh_stocks = NULL;
    StockInfo *sz_stocks = NULL;
    int sh_count = scan_market_file(sh_day_file, "SH", &sh_stocks);
    int sz_count = scan_market_file(sz_day_file, "SZ", &sz_stocks);

    FILE *quotes_csv = fopen(quotes_path, "wb");
    if (!quotes_csv) {
        fprintf(stderr, "无法写入 %s\n", quotes_path);
        free(sh_stocks);
        free(sz_stocks);
        name_map_free();
        write_progress("error", "", 0, 1, "无法写入daily_quotes.csv");
        return 3;
    }
    fprintf(quotes_csv, "symbol,date,open,high,low,close,volume,amount\n");

    int sh_rows = import_market_data(sh_day_file, "SH", sh_stocks, sh_count, quotes_csv, start_date);
    int sz_rows = import_market_data(sz_day_file, "SZ", sz_stocks, sz_count, quotes_csv, start_date);
    fclose(quotes_csv);

    StockInfo *all = (StockInfo *)calloc((size_t)(sh_count + sz_count), sizeof(StockInfo));
    if (all) {
        memcpy(all, sh_stocks, (size_t)sh_count * sizeof(StockInfo));
        memcpy(all + sh_count, sz_stocks, (size_t)sz_count * sizeof(StockInfo));
        write_stocks_csv(stocks_path, all, sh_count + sz_count);
        free(all);
    }
    int sector_rows = 0;
    if (file_exists(sector_file)) {
        sector_rows = export_sector_constituents(sector_file, sector_path);
    }

    char message[256];
    snprintf(message, sizeof(message), "完成：SH %d只/%d行，SZ %d只/%d行，板块成分%d行", sh_count, sh_rows, sz_count, sz_rows, sector_rows);
    write_progress("complete", "", 1, 1, message);
    printf("%s\n输出目录：%s\n", message, output_dir);

    free(sh_stocks);
    free(sz_stocks);
    name_map_free();
    return 0;
}
