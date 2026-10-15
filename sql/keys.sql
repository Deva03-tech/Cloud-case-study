-- Primary keys and indexes on foreign-key columns (run after COPY, before ANALYZE).
ALTER TABLE region   ADD PRIMARY KEY (r_regionkey);
ALTER TABLE nation   ADD PRIMARY KEY (n_nationkey);
ALTER TABLE supplier ADD PRIMARY KEY (s_suppkey);
ALTER TABLE customer ADD PRIMARY KEY (c_custkey);
ALTER TABLE part     ADD PRIMARY KEY (p_partkey);
ALTER TABLE partsupp ADD PRIMARY KEY (ps_partkey, ps_suppkey);
ALTER TABLE orders   ADD PRIMARY KEY (o_orderkey);
ALTER TABLE lineitem ADD PRIMARY KEY (l_orderkey, l_linenumber);

CREATE INDEX idx_nation_regionkey   ON nation   (n_regionkey);
CREATE INDEX idx_supplier_nationkey ON supplier (s_nationkey);
CREATE INDEX idx_customer_nationkey ON customer (c_nationkey);
CREATE INDEX idx_partsupp_suppkey   ON partsupp (ps_suppkey);
CREATE INDEX idx_orders_custkey     ON orders   (o_custkey);
CREATE INDEX idx_lineitem_part_supp ON lineitem (l_partkey, l_suppkey);
CREATE INDEX idx_lineitem_suppkey   ON lineitem (l_suppkey);
