export default {
  title: '上传技能',
  retryHint: '重新上传 {target}：请重新选择该版本对应的 zip 压缩包后提交，系统会安全地续传，不会产生重复发布。',
  description:
    '上传技能目录的 <code>.zip</code> 压缩包（根目录、或单个顶层文件夹内须包含 <code>SKILL.md</code> 和 <code>skill.yaml</code>）。系统会按标准格式校验，并发布为 Forgejo Release —— 与 <code>skillctl publish</code> 效果相同。',
  uploading: '上传中…',
  upload: '上传',
  rejected: '已拒绝：',
  published: '已发布',
  viewRelease: '查看发布',
  indexFailedNote: '注意：搜索索引更新失败（{error}）—— 发布本身已成功。',
}
