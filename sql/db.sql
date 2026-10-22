-- 设置会话字符集为 utf8mb4，防止中文乱码（必须放在最前面）
SET NAMES utf8mb4;

-- 跨境电商经营决策数据库设计
-- 包含：商品信息、订单数据、库存管理
-- 适用于 DeepAgents 结构化数据检索

CREATE DATABASE IF NOT EXISTS crossborder_db;
USE crossborder_db;

-- 1. 商品信息表 (Products)
-- 记录每个 SKU 的成本、售价、毛利、目标市场等经营信息
CREATE TABLE products (
    product_id INT PRIMARY KEY AUTO_INCREMENT,
    sku VARCHAR(50) NOT NULL,            -- SKU 编码
    product_name VARCHAR(100) NOT NULL,  -- 商品名称
    category VARCHAR(50),                -- 类目 (如 3C数码/家居/宠物/户外)
    purchase_cost DECIMAL(10,2),         -- 采购成本 (美元，与售价同币种)
    sale_price DECIMAL(10,2),            -- 销售价 (目标市场币种，如美元)
    gross_margin DECIMAL(5,2),           -- 毛利率 (%)
    supplier VARCHAR(100),               -- 供应商
    platform VARCHAR(50),                -- 平台 (Amazon/TikTok Shop/独立站)
    target_market VARCHAR(50),           -- 目标市场 (美国/德国/日本)
    status VARCHAR(20),                  -- 状态 (在售/下架/测试中)
    description TEXT,                    -- 商品描述/卖点
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 订单表 (Orders)
-- 记录每个商品的销售明细，通过 product_id 关联
CREATE TABLE orders (
    order_id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,

    order_date DATE NOT NULL,            -- 下单日期
    country VARCHAR(50),                 -- 下单国家
    platform VARCHAR(50),                -- 平台
    quantity_sold INT NOT NULL,          -- 销售数量
    unit_price DECIMAL(10,2),            -- 销售单价
    total_amount DECIMAL(15,2),          -- 销售总额
    is_returned TINYINT DEFAULT 0,       -- 是否退货 (0/1)

    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
);

-- 3. 库存表 (Inventory)
-- 记录商品在海外仓/国内仓/平台的库存与在途量，通过 product_id 关联
CREATE TABLE inventory (
    inventory_id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,

    warehouse VARCHAR(50),               -- 仓库 (海外仓/国内仓/亚马逊FBA)
    quantity_on_hand INT DEFAULT 0,      -- 在库量
    quantity_in_transit INT DEFAULT 0,   -- 在途量
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
);

-- ==================== 插入模拟数据 (Mock Data) ====================

-- 1. 插入 8 个商品（采购成本与售价均为美元，毛利率=(售价-成本)/售价 自洽）
INSERT INTO products (sku, product_name, category, purchase_cost, sale_price, gross_margin, supplier, platform, target_market, status, description)
VALUES
('JB-USB-300', '便携榨汁杯', '家居厨房', 11.59, 19.99, 42.00, '深圳凯达电子', 'Amazon', '美国', '在售', 'USB充电便携榨汁杯，350ml容量，主打健康轻食人群。'),
('BT-PRO-5', '无线蓝牙耳机', '3C数码', 17.99, 24.99, 28.00, '东莞声悦科技', 'Amazon', '美国', '在售', '主动降噪无线蓝牙耳机，续航30小时，竞争激烈的红海品类。'),
('PET-DRY-2', '宠物吹水机', '宠物用品', 27.00, 59.99, 55.00, '中山宠乐电器', '独立站', '美国', '在售', '宠物高速吹水机，低噪音，面向养宠家庭。'),
('LAMP-EYE-1', 'LED护眼台灯', '家居', 10.53, 16.99, 38.00, '宁波明视照明', 'Amazon', '德国', '在售', '无频闪LED护眼台灯，德国站主推，需CE认证。'),
('SCALE-K-5', '厨房电子秤', '家居厨房', 6.99, 9.99, 30.00, '深圳凯达电子', 'Amazon', '美国', '在售', '高精度厨房电子秤，5kg量程，走量型低客单商品。'),
('HOLDER-MG-3', '磁吸手机支架', '3C数码', 4.39, 7.99, 45.00, '东莞声悦科技', 'TikTok Shop', '美国', '在售', '磁吸车载手机支架，短视频带货爆款。'),
('CAMP-LED-9', '户外露营灯', '户外', 9.59, 15.99, 40.00, '深圳极光光电', 'Amazon', '日本', '在售', '户外便携露营灯，强季节属性，夏季旺销。'),
('MASS-GUN-1', '筋膜枪', '个护运动', 22.08, 45.99, 52.00, '深圳健康动力', '独立站', '美国', '测试中', '筋膜枪，高毛利但退货率偏高，正在测试期。');

-- 2. 插入库存数据（每种商品 2 个仓位）
INSERT INTO inventory (product_id, warehouse, quantity_on_hand, quantity_in_transit)
VALUES
-- 便携榨汁杯：热销，库存偏低，需补货
(1, '美国海外仓', 1200, 3000),
(1, '国内仓', 800, 2000),
-- 无线蓝牙耳机：销量高但毛利低，库存适中
(2, '美国海外仓', 5000, 4000),
(2, '国内仓', 6000, 0),
-- 宠物吹水机：库存积压（在库+在途都高，销量少）
(3, '美国海外仓', 4500, 3500),
(3, '国内仓', 3000, 1500),
-- LED护眼台灯：德国站，库存健康
(4, '德国海外仓', 2000, 1500),
(4, '国内仓', 1000, 0),
-- 厨房电子秤：走量商品，库存高
(5, '美国海外仓', 8000, 5000),
(5, '国内仓', 5000, 3000),
-- 磁吸手机支架：TikTok 爆款，库存紧张
(6, '美国海外仓', 600, 2000),
(6, '国内仓', 400, 0),
-- 户外露营灯：季节性，淡季积压
(7, '日本海外仓', 3500, 1200),
(7, '国内仓', 2500, 800),
-- 筋膜枪：测试期，库存少
(8, '美国海外仓', 300, 500),
(8, '国内仓', 200, 0);

-- 3. 插入销售订单数据（覆盖 2025 全年，含退货）
INSERT INTO orders (product_id, order_date, country, platform, quantity_sold, unit_price, total_amount, is_returned)
VALUES
-- 便携榨汁杯：持续热销
(1, '2025-03-10', '美国', 'Amazon', 800, 19.99, 15992.00, 0),
(1, '2025-06-20', '美国', 'Amazon', 1500, 19.99, 29985.00, 0),
(1, '2025-09-15', '美国', 'Amazon', 1200, 19.99, 23988.00, 1),
(1, '2025-11-25', '美国', 'Amazon', 2000, 18.99, 37980.00, 0),

-- 无线蓝牙耳机：销量高但退货多、毛利低
(2, '2025-02-18', '美国', 'Amazon', 2000, 24.99, 49980.00, 0),
(2, '2025-05-12', '美国', 'Amazon', 1800, 24.99, 44982.00, 1),
(2, '2025-08-30', '美国', 'Amazon', 2200, 23.99, 52778.00, 1),
(2, '2025-12-08', '美国', 'Amazon', 2500, 23.99, 59975.00, 0),

-- 宠物吹水机：销量少（积压信号）
(3, '2025-04-05', '美国', '独立站', 120, 59.99, 7198.80, 0),
(3, '2025-07-22', '美国', '独立站', 80, 59.99, 4799.20, 1),
(3, '2025-10-11', '美国', '独立站', 150, 56.99, 8548.50, 0),

-- LED护眼台灯：德国站稳定
(4, '2025-03-01', '德国', 'Amazon', 500, 16.99, 8495.00, 0),
(4, '2025-06-15', '德国', 'Amazon', 700, 16.99, 11893.00, 0),
(4, '2025-09-10', '德国', 'Amazon', 650, 16.99, 11043.50, 1),
(4, '2025-11-20', '德国', 'Amazon', 900, 15.99, 14391.00, 0),

-- 厨房电子秤：走量
(5, '2025-01-15', '美国', 'Amazon', 3000, 9.99, 29970.00, 0),
(5, '2025-04-20', '美国', 'Amazon', 3500, 9.99, 34965.00, 0),
(5, '2025-07-18', '美国', 'Amazon', 4000, 9.49, 37960.00, 0),
(5, '2025-10-05', '美国', 'Amazon', 4500, 9.49, 42705.00, 1),

-- 磁吸手机支架：TikTok 爆款
(6, '2025-05-08', '美国', 'TikTok Shop', 5000, 7.99, 39950.00, 0),
(6, '2025-08-16', '美国', 'TikTok Shop', 8000, 7.49, 59920.00, 1),
(6, '2025-11-02', '美国', 'TikTok Shop', 10000, 6.99, 69900.00, 0),

-- 户外露营灯：季节性（夏季旺、冬季淡）
(7, '2025-05-20', '日本', 'Amazon', 800, 15.99, 12792.00, 0),
(7, '2025-07-15', '日本', 'Amazon', 1200, 15.99, 19188.00, 0),
(7, '2025-12-10', '日本', 'Amazon', 200, 14.99, 2998.00, 0),

-- 筋膜枪：测试期销量少、退货高
(8, '2025-09-01', '美国', '独立站', 60, 45.99, 2759.40, 1),
(8, '2025-11-15', '美国', '独立站', 90, 45.99, 4139.10, 1);
