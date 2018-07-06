--
-- Table structure for table `objects`
--

DROP TABLE IF EXISTS `objects`;
CREATE TABLE `objects` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `key` varchar(256) CHARACTER SET utf8 COLLATE utf8_bin NOT NULL,
  `uploading` tinyint(1) NOT NULL DEFAULT '0',
  `created` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `deleteAfter` datetime DEFAULT NULL,
  `user` text CHARACTER SET utf8 COLLATE utf8_bin,
  `name` text CHARACTER SET utf8 COLLATE utf8_bin,
  `mimeType` text CHARACTER SET utf8 COLLATE utf8_bin,
  `pri` tinyint(1) NOT NULL DEFAULT '0',
  `sec` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `handle` (`key`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

